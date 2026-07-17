import unittest
from dataclasses import replace

from vision_app.settings import CalibrationConfirmation, ControlSettings, SettingsError


class SettingsTests(unittest.TestCase):
    def test_defaults_are_valid_but_not_automatically_confirmed(self):
        settings = ControlSettings().validated()
        confirmation = CalibrationConfirmation()
        self.assertEqual(settings.pixels_per_meter, 120.0)
        self.assertEqual(settings.rpm_per_mps, 1.0)
        self.assertFalse(confirmation.is_confirmed_for(settings))

    def test_calibration_confirmation_is_invalid_after_critical_change(self):
        settings = ControlSettings().validated()
        confirmation = CalibrationConfirmation()
        confirmation.confirm(settings)
        self.assertTrue(confirmation.is_confirmed_for(settings))
        self.assertFalse(confirmation.is_confirmed_for(replace(settings, rpm_per_mps=2.0)))

    def test_illegal_settings_are_rejected(self):
        for settings in (
            ControlSettings(pixels_per_meter=0),
            ControlSettings(rpm_per_mps=-1),
            ControlSettings(camera_axis_sign=0),
            ControlSettings(motor_axis_sign=2),
            ControlSettings(rpm_limit=2048),
            ControlSettings(displacement_window_size=2),
            ControlSettings(command_interval_s=0.5),
        ):
            with self.subTest(settings=settings), self.assertRaises(SettingsError):
                settings.validated()

        with self.assertRaises(SettingsError):
            ControlSettings(
                backend="arduino_serial",
                serial_port="COM_TEST",
                control_mode="ino_pid_compat",
            ).validated()


if __name__ == "__main__":
    unittest.main()
