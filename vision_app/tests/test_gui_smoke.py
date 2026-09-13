import os
import time
import unittest
from unittest.mock import patch

from vision_app.safety import AppState
from vision_app.swimming_app import SwimControlApp


@unittest.skipUnless(os.environ.get("DISPLAY"), "需要图形显示环境")
class GuiSmokeTests(unittest.TestCase):
    def tear_down_app(self, app):
        app._closing = True
        app.gateway.close()
        app.frame_source.close()
        app.root.destroy()

    def test_virtual_backend_connects_through_supervisor(self):
        app = SwimControlApp()
        try:
            app.backend_var.set("virtual"); app._on_backend_selected(); app.connect_motor()
            app.root.update_idletasks()
            self.assertTrue(app.gateway.connected)
            self.assertIn("virtual", app.backend_badge_var.get())
            self.assertFalse(app.gateway.is_real)
            self.assertEqual(str(app.open_camera_button.cget("state")), "normal")
        finally:
            self.tear_down_app(app)

    def test_camera_scan_results_populate_editable_source_box(self):
        app = SwimControlApp()
        try:
            app.camera_source_var.set("rtsp://example.invalid/live")
            app._scan_running = True
            app._scan_results.put((["0", "2"], None))
            app._consume_camera_scan_results()
            self.assertFalse(app._scan_running)
            self.assertEqual(app.camera_source_box.cget("values"), ("0", "2", "rtsp://example.invalid/live"))
        finally:
            self.tear_down_app(app)

    def test_manual_speed_runs_without_camera_until_stop(self):
        app = SwimControlApp()
        try:
            app.backend_var.set("virtual"); app._on_backend_selected(); app.connect_motor()
            deadline = time.monotonic() + 2.0
            while app.latest_measured_rpm is None and time.monotonic() < deadline:
                app._poll_motor_events(); app.root.update_idletasks(); time.sleep(0.02)
            app.rpm_per_mps_var.set("120.0"); app.manual_speed_var.set("0.5"); app.operation_mode_var.set("manual_speed")
            settings = app._settings_from_ui(); app.settings = settings; app.calibration.confirm(settings)
            with patch("vision_app.swimming_app.messagebox.askyesno", return_value=True): app.start_control()
            self.assertEqual(app.safety.state, AppState.RUNNING)
            app.manual_stop()
            self.assertEqual(app.safety.state, AppState.STOPPED)
        finally:
            self.tear_down_app(app)


if __name__ == "__main__": unittest.main()
