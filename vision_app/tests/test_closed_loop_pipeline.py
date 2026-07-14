import unittest

from vision_app.control_core import RelativeDisplacementEstimator, solve_motion
from vision_app.motor_link import encode_target_rpm


class ClosedLoopPipelineTests(unittest.TestCase):
    def test_relative_displacement_to_ino_target_command(self):
        estimator = RelativeDisplacementEstimator(
            pixels_per_meter=100.0,
            camera_axis_sign=1,
            max_samples=7,
            max_age_s=1.0,
        )
        estimator.add_sample(10.0, 0.0)
        estimator.add_sample(10.1, 5.0)
        estimate = estimator.add_sample(10.2, 10.0)

        self.assertTrue(estimate.ready)
        self.assertAlmostEqual(estimate.relative_speed_mps, 0.5)

        solution = solve_motion(
            actual_rpm=100.0,
            relative_speed_mps=estimate.relative_speed_mps,
            rpm_per_mps=100.0,
            motor_axis_sign=1,
            rpm_limit=2047,
        )

        self.assertAlmostEqual(solution.robot_speed_mps, 1.0)
        self.assertAlmostEqual(solution.swimmer_speed_mps, 1.5)
        self.assertEqual(solution.command_rpm, 150)
        self.assertEqual(encode_target_rpm(solution.command_rpm), b"T150\n")

    def test_co_speed_has_zero_relative_slope_and_keeps_robot_target(self):
        estimator = RelativeDisplacementEstimator(120.0, 1, max_age_s=1.0)
        estimator.add_sample(1.0, 30.0)
        estimator.add_sample(1.1, 30.0)
        estimate = estimator.add_sample(1.2, 30.0)

        solution = solve_motion(250.0, estimate.relative_speed_mps, 100.0, 1, 2047)
        self.assertAlmostEqual(estimate.relative_speed_mps, 0.0)
        self.assertAlmostEqual(solution.swimmer_speed_mps, 2.5)
        self.assertEqual(solution.command_rpm, 250)


if __name__ == "__main__":
    unittest.main()
