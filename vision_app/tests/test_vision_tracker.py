import tempfile
import unittest
from pathlib import Path

from vision_app.vision_tracker import VisionInputError, parse_video_source


class VideoSourceParsingTests(unittest.TestCase):
    def test_numeric_camera_index(self):
        source = parse_video_source(" 0 ")
        self.assertEqual(source.open_value, 0)
        self.assertFalse(source.offline_file)

    def test_url_is_not_marked_as_offline_file(self):
        source = parse_video_source("rtsp://camera.local/live")
        self.assertEqual(source.open_value, "rtsp://camera.local/live")
        self.assertFalse(source.offline_file)

    def test_existing_local_file_is_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.mp4"
            path.touch()
            source = parse_video_source(str(path))
            self.assertTrue(source.offline_file)
            self.assertEqual(Path(source.open_value), path.resolve())

    def test_empty_and_negative_camera_index_are_rejected(self):
        for value in ("", "   ", "-1"):
            with self.subTest(value=value), self.assertRaises(VisionInputError):
                parse_video_source(value)


if __name__ == "__main__":
    unittest.main()
