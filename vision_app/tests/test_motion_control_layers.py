import unittest

from vision_app.motion_control import MotionControlConfig, MotionController
from vision_app.target_tracking import TargetObservation


def observation(timestamp, center_x, width=200):
    return TargetObservation(timestamp, width, 100, center_x, 50.0, (0, 0, 10, 10))


class MotionLayerTests(unittest.TestCase):
    def test_position_mode_applies_reference_direction_deadband_and_limit(self):
        controller = MotionController(MotionControlConfig(
            mode="position_follow", pixels_per_meter=100, camera_axis_sign=-1,
            target_offset_px=10, position_kp=2, deadband_m=0.05, max_speed_mps=0.4,
        ))
        inside = controller.compute(observation(1.0, 113))
        self.assertEqual(inside.expected_speed_mps, 0.0)
        outside = controller.compute(observation(2.0, 140))
        self.assertAlmostEqual(outside.error_m, -0.3)
        self.assertEqual(outside.expected_speed_mps, -0.4)

    def test_velocity_mode_uses_command_estimate_and_reset_clears_window(self):
        controller = MotionController(MotionControlConfig(
            mode="velocity_estimate_follow", pixels_per_meter=100,
            rpm_per_mps=100, motor_axis_sign=1, max_speed_mps=5,
            estimator_window_size=5, estimator_window_s=1,
        ))
        controller.compute(observation(1.0, 100), 100)
        controller.compute(observation(1.1, 105), 100)
        result = controller.compute(observation(1.2, 110), 100)
        self.assertTrue(result.ready)
        self.assertAlmostEqual(result.relative_speed_mps, 0.5)
        self.assertAlmostEqual(result.estimated_robot_speed_mps, 1.0)
        self.assertAlmostEqual(result.expected_speed_mps, 1.5)
        controller.reset()
        self.assertFalse(controller.compute(observation(2.0, 100), 100).ready)
