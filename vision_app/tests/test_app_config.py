import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from vision_app.app_config import AppConfigError, load_settings, save_settings
from vision_app.settings import ControlSettings


class AppConfigTests(unittest.TestCase):
    def test_round_trip_preserves_backend_and_calibration_not_arm_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = replace(
                ControlSettings(),
                backend="python_can",
                can_interface="pcan",
                can_channel="PCAN_USBBUS1",
                rpm_per_mps=88.0,
            )
            save_settings(settings, path)
            loaded = load_settings(path)
            self.assertEqual(loaded.backend, "python_can")
            self.assertEqual(loaded.can_channel, "PCAN_USBBUS1")
            self.assertEqual(loaded.rpm_per_mps, 88.0)
            self.assertNotIn("armed", path.read_text(encoding="utf-8"))

    def test_invalid_config_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(AppConfigError):
                load_settings(path)


if __name__ == "__main__":
    unittest.main()
