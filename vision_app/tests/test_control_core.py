import math
import unittest

from vision_app.control_core import (
    ControlInputError,
    RelativeDisplacementEstimator,
    RpmRateLimiter,
    solve_motion,
)


class RelativeDisplacementEstimatorTests(unittest.TestCase):
    def test_linear_relative_displacement_produces_relative_speed(self):
        estimator = RelativeDisplacementEstimator(
            pixels_per_meter=100.0,
            camera_axis_sign=1,
            max_samples=7,
            max_age_s=1.0,
        )

        first = estimator.add_sample(10.0, 0.0)
        second = estimator.add_sample(10.1, 5.0)
        third = estimator.add_sample(10.2, 10.0)

        self.assertFalse(first.ready)
        self.assertFalse(second.ready)
        self.assertTrue(third.ready)
        self.assertAlmostEqual(third.relative_displacement_m, 0.1)
        self.assertAlmostEqual(third.relative_speed_mps, 0.5, places=9)

    def test_camera_axis_sign_changes_displacement_and_speed_direction(self):
        estimator = RelativeDisplacementEstimator(100.0, -1, max_age_s=1.0)
        estimator.add_sample(0.0, 0.0)
        estimator.add_sample(0.1, 5.0)
        result = estimator.add_sample(0.2, 10.0)

        self.assertAlmostEqual(result.relative_displacement_m, -0.1)
        self.assertAlmostEqual(result.relative_speed_mps, -0.5, places=9)

    def test_non_increasing_timestamp_is_rejected_without_corrupting_window(self):
        estimator = RelativeDisplacementEstimator(100.0, 1)
        estimator.add_sample(1.0, 0.0)

        with self.assertRaises(ControlInputError):
            estimator.add_sample(1.0, 1.0)

        self.assertEqual(estimator.sample_count, 1)

    def test_non_finite_sample_is_rejected(self):
        estimator = RelativeDisplacementEstimator(100.0, 1)
        with self.assertRaises(ControlInputError):
            estimator.add_sample(math.nan, 0.0)
        with self.assertRaises(ControlInputError):
            estimator.add_sample(1.0, math.inf)

    def test_reset_removes_all_history(self):
        estimator = RelativeDisplacementEstimator(100.0, 1)
        estimator.add_sample(1.0, 0.0)
        estimator.reset()
        self.assertEqual(estimator.sample_count, 0)


class MotionSolverTests(unittest.TestCase):
    def test_stationary_robot_and_positive_relative_speed(self):
        result = solve_motion(
            actual_rpm=0.0,
            relative_speed_mps=0.5,
            rpm_per_mps=100.0,
            motor_axis_sign=1,
            rpm_limit=2047,
        )
        self.assertAlmostEqual(result.robot_speed_mps, 0.0)
        self.assertAlmostEqual(result.swimmer_speed_mps, 0.5)
        self.assertEqual(result.command_rpm, 50)

    def test_robot_speed_plus_negative_relative_speed(self):
        result = solve_motion(100.0, -0.2, 100.0, 1, 2047)
        self.assertAlmostEqual(result.robot_speed_mps, 1.0)
        self.assertAlmostEqual(result.swimmer_speed_mps, 0.8)
        self.assertEqual(result.command_rpm, 80)

    def test_negative_robot_speed_plus_positive_relative_speed(self):
        result = solve_motion(-70.0, 0.1, 100.0, 1, 2047)
        self.assertAlmostEqual(result.robot_speed_mps, -0.7)
        self.assertAlmostEqual(result.swimmer_speed_mps, -0.6)
        self.assertEqual(result.command_rpm, -60)

    def test_zero_relative_speed_commands_current_robot_speed(self):
        result = solve_motion(123.0, 0.0, 100.0, 1, 2047)
        self.assertAlmostEqual(result.swimmer_speed_mps, 1.23)
        self.assertEqual(result.command_rpm, 123)

    def test_motor_axis_sign_round_trip(self):
        result = solve_motion(-100.0, 0.5, 100.0, -1, 2047)
        self.assertAlmostEqual(result.robot_speed_mps, 1.0)
        self.assertAlmostEqual(result.swimmer_speed_mps, 1.5)
        self.assertEqual(result.command_rpm, -150)

    def test_protocol_limit_is_applied_and_reported(self):
        result = solve_motion(0.0, 30.0, 100.0, 1, 2047)
        self.assertEqual(result.raw_target_rpm, 3000.0)
        self.assertEqual(result.command_rpm, 2047)
        self.assertTrue(result.saturated)

    def test_illegal_parameters_are_rejected(self):
        invalid_calls = [
            dict(actual_rpm=0, relative_speed_mps=0, rpm_per_mps=0, motor_axis_sign=1, rpm_limit=2047),
            dict(actual_rpm=0, relative_speed_mps=0, rpm_per_mps=1, motor_axis_sign=0, rpm_limit=2047),
            dict(actual_rpm=0, relative_speed_mps=math.nan, rpm_per_mps=1, motor_axis_sign=1, rpm_limit=2047),
            dict(actual_rpm=True, relative_speed_mps=0, rpm_per_mps=1, motor_axis_sign=1, rpm_limit=2047),
        ]
        for kwargs in invalid_calls:
            with self.subTest(kwargs=kwargs), self.assertRaises(ControlInputError):
                solve_motion(**kwargs)


class RpmRateLimiterTests(unittest.TestCase):
    def test_rate_limit_starts_from_zero_and_limits_both_directions(self):
        limiter = RpmRateLimiter(max_rate_rpm_per_s=100.0)
        self.assertEqual(limiter.update(50.0, 1.0), 0.0)
        self.assertAlmostEqual(limiter.update(50.0, 1.1), 10.0)
        self.assertAlmostEqual(limiter.update(-50.0, 1.2), 0.0)

    def test_reset_returns_to_safe_zero(self):
        limiter = RpmRateLimiter(100.0)
        limiter.update(100.0, 1.0)
        limiter.update(100.0, 2.0)
        limiter.reset()
        self.assertEqual(limiter.update(100.0, 3.0), 0.0)


if __name__ == "__main__":
    unittest.main()
