from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from vision_app.control_core import RelativeDisplacementEstimator
from vision_app.target_tracking import TargetObservation


class MotionControlError(ValueError):
    pass


class FollowMode(str, Enum):
    POSITION = "position_follow"
    VELOCITY_ESTIMATE = "velocity_estimate_follow"


@dataclass(frozen=True)
class MotionControlConfig:
    mode: str = FollowMode.POSITION.value
    pixels_per_meter: float = 120.0
    camera_axis_sign: int = 1
    target_offset_px: float = 0.0
    position_kp: float = 1.0
    deadband_m: float = 0.05
    max_speed_mps: float = 1.0
    rpm_per_mps: float = 1.0
    motor_axis_sign: int = 1
    estimator_window_size: int = 7
    estimator_window_s: float = 0.30
    max_offset_fraction: float = 0.45

    def validated(self) -> "MotionControlConfig":
        FollowMode(self.mode)
        positive = {
            "pixels_per_meter": self.pixels_per_meter,
            "position_kp": self.position_kp,
            "max_speed_mps": self.max_speed_mps,
            "rpm_per_mps": self.rpm_per_mps,
            "estimator_window_s": self.estimator_window_s,
        }
        for name, value in positive.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise MotionControlError(f"{name} 必须是正有限数")
        if not math.isfinite(self.target_offset_px):
            raise MotionControlError("target_offset_px 必须是有限数")
        if not math.isfinite(self.deadband_m) or self.deadband_m < 0:
            raise MotionControlError("deadband_m 必须是非负有限数")
        if not math.isfinite(self.max_offset_fraction) or not 0 < self.max_offset_fraction < 0.5:
            raise MotionControlError("max_offset_fraction 必须位于 0..0.5")
        if self.camera_axis_sign not in (-1, 1) or self.motor_axis_sign not in (-1, 1):
            raise MotionControlError("方向只能是 -1 或 +1")
        if isinstance(self.estimator_window_size, bool) or not isinstance(self.estimator_window_size, int) or self.estimator_window_size < 3:
            raise MotionControlError("估算窗口样本数至少为 3")
        return self


@dataclass(frozen=True)
class MotionSetpoint:
    ready: bool
    mode: str
    error_px: float
    error_m: float
    expected_speed_mps: float | None
    relative_speed_mps: float | None = None
    estimated_robot_speed_mps: float | None = None
    reason: str | None = None
    outside_safe_region: bool = False


class MotionController:
    """Layer 2 pure motion strategy coordinator."""

    def __init__(self, config: MotionControlConfig) -> None:
        self.config = config.validated()
        self._estimator = self._new_estimator()

    def _new_estimator(self) -> RelativeDisplacementEstimator:
        return RelativeDisplacementEstimator(
            self.config.pixels_per_meter,
            self.config.camera_axis_sign,
            max_samples=self.config.estimator_window_size,
            max_age_s=self.config.estimator_window_s,
        )

    def reset(self) -> None:
        self._estimator = self._new_estimator()

    def compute(self, observation: TargetObservation, commanded_rpm_estimate: int = 0) -> MotionSetpoint:
        config = self.config
        reference_x = observation.frame_width / 2.0 + config.target_offset_px
        error_px = observation.target_center_x - reference_x
        error_m = config.camera_axis_sign * error_px / config.pixels_per_meter
        outside = abs(error_px) > observation.frame_width * config.max_offset_fraction
        if config.mode == FollowMode.POSITION.value:
            speed = 0.0 if abs(error_m) <= config.deadband_m else config.position_kp * error_m
            speed = max(-config.max_speed_mps, min(config.max_speed_mps, speed))
            return MotionSetpoint(True, config.mode, error_px, error_m, speed, outside_safe_region=outside)

        estimate = self._estimator.add_sample(observation.timestamp, error_px)
        if not estimate.ready or estimate.relative_speed_mps is None:
            return MotionSetpoint(False, config.mode, error_px, error_m, None, reason=estimate.reason, outside_safe_region=outside)
        robot_speed = config.motor_axis_sign * commanded_rpm_estimate / config.rpm_per_mps
        speed = robot_speed + estimate.relative_speed_mps
        speed = max(-config.max_speed_mps, min(config.max_speed_mps, speed))
        return MotionSetpoint(
            True,
            config.mode,
            error_px,
            error_m,
            speed,
            estimate.relative_speed_mps,
            robot_speed,
            outside_safe_region=outside,
        )
