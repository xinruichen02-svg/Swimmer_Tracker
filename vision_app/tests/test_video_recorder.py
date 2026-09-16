import tempfile
import unittest
from pathlib import Path

from vision_app.video_recorder import VideoRecorder, VideoRecorderError


class FakeFrame:
    shape = (360, 640, 3)


class FakeWriter:
    def __init__(self, opened=True):
        self.opened = opened
        self.frames = []
        self.released = False

    def isOpened(self):
        return self.opened

    def write(self, frame):
        self.frames.append(frame)

    def release(self):
        self.released = True


class VideoRecorderTests(unittest.TestCase):
    def test_custom_path_write_and_stop(self):
        writer = FakeWriter()
        calls = []

        def factory(*args):
            calls.append(args)
            return writer

        with tempfile.TemporaryDirectory() as folder:
            recorder = VideoRecorder(factory)
            target = recorder.start(Path(folder) / "session.mp4", (640, 360), 25.0)
            recorder.write(FakeFrame())
            result = recorder.stop()

        self.assertEqual(target.name, "session.mp4")
        self.assertEqual(calls[0][2:], (25.0, (640, 360)))
        self.assertEqual(result.frame_count, 1)
        self.assertTrue(writer.released)
        self.assertFalse(recorder.is_recording)

    def test_missing_extension_defaults_to_mp4(self):
        writer = FakeWriter()
        with tempfile.TemporaryDirectory() as folder:
            target = VideoRecorder(lambda *_args: writer).start(
                Path(folder) / "analysis", (640, 360), 30.0
            )
        self.assertEqual(target.suffix, ".mp4")

    def test_rejects_writer_failure_and_size_change(self):
        with tempfile.TemporaryDirectory() as folder:
            failed = FakeWriter(opened=False)
            with self.assertRaises(VideoRecorderError):
                VideoRecorder(lambda *_args: failed).start(
                    Path(folder) / "bad.mp4", (640, 360), 30.0
                )
            writer = FakeWriter()
            recorder = VideoRecorder(lambda *_args: writer)
            recorder.start(Path(folder) / "ok.mp4", (320, 240), 30.0)
            with self.assertRaises(VideoRecorderError):
                recorder.write(FakeFrame())
            recorder.stop()


if __name__ == "__main__":
    unittest.main()
