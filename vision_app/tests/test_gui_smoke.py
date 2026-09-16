import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from vision_app.frame_source import FrameSample
from vision_app.safety import AppState
from vision_app.swimming_app import SwimControlApp
from vision_app.target_tracking import TargetObservation
from vision_app.video_recorder import VideoRecorder


class FakeOfflineSource:
    def __init__(self):
        self.source = None
        self.is_open = False
        self.fps = 25.0

    def open(self, raw):
        self.source = SimpleNamespace(raw=raw, offline_file=True)
        self.is_open = True
        return FrameSample(np.zeros((120, 200, 3), dtype=np.uint8), 1.0, 200, 120)

    def close(self):
        self.source = None
        self.is_open = False


class FakeTracker:
    def __init__(self):
        self.locked = False

    def clear(self):
        self.locked = False

    def select_bbox(self, sample):
        return (70, 40, 60, 40)

    def initialize(self, sample, bbox):
        self.locked = True
        x, y, width, height = bbox
        return TargetObservation(sample.timestamp, sample.width, sample.height, x + width / 2, y + height / 2, bbox)

    def update(self, sample):
        if not self.locked:
            return None
        return TargetObservation(sample.timestamp, sample.width, sample.height, 100.0, 60.0, (70, 40, 60, 40))


class FakeWriter:
    def __init__(self):
        self.frames = []
        self.released = False

    def isOpened(self): return True
    def write(self, frame): self.frames.append(frame)
    def release(self): self.released = True


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "需要图形显示环境")
class GuiSmokeTests(unittest.TestCase):
    def tear_down_app(self, app):
        app._closing = True
        app.gateway.close()
        app.frame_source.close()
        app.recorder.stop()
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

    def test_offline_video_analysis_does_not_require_motor(self):
        app = SwimControlApp()
        try:
            app.frame_source = FakeOfflineSource()
            app.target_tracker = FakeTracker()
            app._open_media(str(Path("sample.mp4").resolve()), pause_offline=True)
            self.assertFalse(app.gateway.connected)
            self.assertTrue(app._media_paused)
            self.assertTrue(app.source_kind_var.get().startswith("离线视频 · "))

            app.select_target()
            self.assertTrue(app.target_tracker.locked)
            self.assertIn("开始分析", app.detail_var.get())
            app.toggle_analysis()
            self.assertFalse(app._media_paused)
            self.assertIsNotNone(app._playback_next_due)
            self.assertIn("正在分析", app.media_status_var.get())
        finally:
            self.tear_down_app(app)

    def test_recording_uses_selected_save_path(self):
        app = SwimControlApp()
        writer = FakeWriter()
        try:
            app.frame_source = FakeOfflineSource()
            app._open_media(str(Path("sample.mp4").resolve()), pause_offline=True)
            app.recorder = VideoRecorder(lambda *_args: writer)
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "custom-output.mp4"
                with patch("vision_app.swimming_app.filedialog.asksaveasfilename", return_value=str(target)):
                    app.toggle_recording()
                self.assertTrue(app.recorder.is_recording)
                self.assertEqual(app.recorder.path, target.resolve())
                app.recorder.write(app.latest_sample.image)
                app.toggle_recording()
                self.assertIn("custom-output.mp4", app.record_path_var.get())
                self.assertFalse(app.recorder.is_recording)
                self.assertTrue(writer.released)
        finally:
            self.tear_down_app(app)


if __name__ == "__main__": unittest.main()
