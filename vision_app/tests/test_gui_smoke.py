import unittest
import time
from unittest.mock import patch

from vision_app.safety import AppState
from vision_app.swimming_app import SwimControlApp


class GuiSmokeTests(unittest.TestCase):
    def test_virtual_backend_is_explicit_and_connects_through_supervisor(self):
        app = SwimControlApp()
        try:
            app.backend_var.set("virtual")
            app._on_backend_selected()
            app.connect_serial()
            app.root.update_idletasks()
            self.assertTrue(app.motor.connected)
            self.assertIn("仿真模式", app.backend_badge_var.get())
            self.assertFalse(app.motor.is_real)
            self.assertIn("摄像头源", app.video_label.cget("text"))
            self.assertEqual(str(app.open_camera_button.cget("state")), "normal")
            self.assertEqual(app.open_camera_button.winfo_parent(), app.camera_source_box.winfo_parent())
            self.assertEqual(str(app.apply_pid_button.cget("state")), "disabled")
        finally:
            app._closing = True
            app.motor.disconnect(send_stop=True)
            app.vision.release()
            app.root.destroy()

    def test_camera_scan_results_populate_editable_source_box(self):
        app = SwimControlApp()
        try:
            app.camera_source_var.set("rtsp://example.invalid/live")
            app._camera_scan_running = True
            app._camera_scan_results.put((["0", "2"], None))

            app._consume_camera_scan_results()

            self.assertFalse(app._camera_scan_running)
            self.assertEqual(app.camera_source_box.cget("values"), ("0", "2", "rtsp://example.invalid/live"))
            self.assertIn("0, 2", app.detail_var.get())
        finally:
            app._closing = True
            app.motor.disconnect(send_stop=True)
            app.vision.release()
            app.root.destroy()

    def test_constant_speed_mode_runs_without_camera_until_stop(self):
        app = SwimControlApp()
        try:
            app.backend_var.set("virtual")
            app._on_backend_selected()
            app.connect_serial()
            deadline = time.monotonic() + 2.0
            while app.latest_telemetry is None and time.monotonic() < deadline:
                app._poll_motor_events()
                app.root.update_idletasks()
                time.sleep(0.02)
            self.assertIsNotNone(app.latest_telemetry)

            app.rpm_per_mps_var.set("120.0")
            app.constant_speed_var.set("0.5")
            settings = app._settings_from_ui()
            app.settings = settings
            app.calibration.confirm(settings)
            app.calibration_status_var.set("已确认")

            with patch("vision_app.swimming_app.messagebox.askyesno", return_value=True):
                app.start_constant_speed()

            self.assertEqual(app.safety.state, AppState.RUNNING)
            self.assertEqual(app.active_run_mode, "constant")
            self.assertEqual(app.constant_command_rpm, 60)
            self.assertFalse(app.vision.is_open)

            app.manual_stop()
            self.assertEqual(app.safety.state, AppState.STOPPED)
            self.assertIsNone(app.active_run_mode)
        finally:
            app._closing = True
            app.motor.disconnect(send_stop=True)
            app.vision.release()
            app.root.destroy()


if __name__ == "__main__":
    unittest.main()
