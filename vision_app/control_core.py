from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


class ControlInputError(ValueError):
    """Raised when a value cannot safely participate in control."""


def _finite_real(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlInputError(f"{name} 必须是数字")
    result = float(value)
    if not math.isfinite(result):
        raise ControlInputError(f"{name} 必须是有限数字")
    return result


def _positive_real(name: str, value: object) -> float:
    result = _finite_real(name, value)
    if result <= 0.0:
        raise ControlInputError(f"{name} 必须大于 0")
    return result


def _axis_sign(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in (-1, 1):
        raise ControlInputError(f"{name} 只能是 -1 或 +1")
    return value


@dataclass(frozen=True)
class RelativeMotionEstimate:
    ready: bool
    relative_displacement_m: float
    relative_speed_mps: float | None
    sample_count: int
    reason: str | None = None


class RelativeDisplacementEstimator:
    """Derive signed relative speed from timestamped relative displacement."""

    def __init__(
        self,
        pixels_per_meter: float,
        camera_axis_sign: int,
        *,
        max_samples: int = 7,
        max_age_s: float = 0.30,
    ) -> None:
        self.pixels_per_meter = _positive_real("pixels_per_meter", pixels_per_meter)
        self.camera_axis_sign = _axis_sign("camera_axis_sign", camera_axis_sign)
        if isinstance(max_samples, bool) or not isinstance(max_samples, int) or max_samples < 3:
            raise ControlInputError("max_samples 必须是至少为 3 的整数")
        self.max_samples = max_samples
        self.max_age_s = _positive_real("max_age_s", max_age_s)
        self._samples: deque[tuple[float, float]] = deque(maxlen=max_samples)

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def reset(self) -> None:
        self._samples.clear()

    def add_sample(self, timestamp: float, offset_px: float) -> RelativeMotionEstimate:
        timestamp_value = _finite_real("timestamp", timestamp)
        offset_value = _finite_real("offset_px", offset_px)
        if self._samples and timestamp_value <= self._samples[-1][0]:
            raise ControlInputError("相对位移时间戳必须严格递增")

        displacement_m = self.camera_axis_sign * offset_value / self.pixels_per_meter
        self._samples.append((timestamp_value, displacement_m))
        cutoff = timestamp_value - self.max_age_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

        if len(self._samples) < 3:
            return RelativeMotionEstimate(
                ready=False,
                relative_displacement_m=displacement_m,
                relative_speed_mps=None,
                sample_count=len(self._samples),
                reason="相对位移样本不足",
            )

        base_time = self._samples[0][0]
        xs = [sample_time - base_time for sample_time, _ in self._samples]
        ys = [sample_displacement for _, sample_displacement in self._samples]
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator <= 1e-15:
            return RelativeMotionEstimate(
                ready=False,
                relative_displacement_m=displacement_m,
                relative_speed_mps=None,
                sample_count=len(self._samples),
                reason="相对位移时间跨度不足",
            )
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        relative_speed = numerator / denominator
        if not math.isfinite(relative_speed):
            raise ControlInputError("相对速度计算结果不是有限数字")
        return RelativeMotionEstimate(
            ready=True,
            relative_displacement_m=displacement_m,
            relative_speed_mps=relative_speed,
            sample_count=len(self._samples),
        )


@dataclass(frozen=True)
class MotionSolution:
    robot_speed_mps: float
    relative_speed_mps: float
    swimmer_speed_mps: float
    raw_target_rpm: float
    command_rpm: int
    saturated: bool


def constant_speed_to_rpm(
    speed_mps: float,
    rpm_per_mps: float,
    motor_axis_sign: int,
    rpm_limit: int,
) -> int:
    """Convert a signed robot linear-speed setpoint into a safe motor RPM command."""
    speed = _finite_real("constant_speed_mps", speed_mps)
    conversion = _positive_real("rpm_per_mps", rpm_per_mps)
    sign = _axis_sign("motor_axis_sign", motor_axis_sign)
    if isinstance(rpm_limit, bool) or not isinstance(rpm_limit, int) or not 1 <= rpm_limit <= 2047:
        raise ControlInputError("rpm_limit 必须是 1..2047 范围内的整数")
    raw_rpm = sign * speed * conversion
    if abs(raw_rpm) > rpm_limit:
        max_speed = rpm_limit / conversion
        raise ControlInputError(f"定速目标超出RPM上限；当前最大线速度约为 ±{max_speed:.3f} m/s")
    command = int(round(raw_rpm))
    if speed != 0.0 and command == 0:
        raise ControlInputError("定速目标过小，换算后不足 1 RPM")
    return command


def solve_motion(
    actual_rpm: float,
    relative_speed_mps: float,
    rpm_per_mps: float,
    motor_axis_sign: int,
    rpm_limit: int,
) -> MotionSolution:
    actual = _finite_real("actual_rpm", actual_rpm)
    relative = _finite_real("relative_speed_mps", relative_speed_mps)
    conversion = _positive_real("rpm_per_mps", rpm_per_mps)
    sign = _axis_sign("motor_axis_sign", motor_axis_sign)
    if isinstance(rpm_limit, bool) or not isinstance(rpm_limit, int) or not 1 <= rpm_limit <= 2047:
        raise ControlInputError("rpm_limit 必须是 1..2047 范围内的整数")

    robot_speed = sign * actual / conversion
    swimmer_speed = robot_speed + relative
    raw_target = sign * swimmer_speed * conversion
    limited_target = max(-float(rpm_limit), min(float(rpm_limit), raw_target))
    saturated = not math.isclose(raw_target, limited_target, rel_tol=0.0, abs_tol=1e-12)
    command = int(round(limited_target))
    command = max(-rpm_limit, min(rpm_limit, command))
    return MotionSolution(
        robot_speed_mps=robot_speed,
        relative_speed_mps=relative,
        swimmer_speed_mps=swimmer_speed,
        raw_target_rpm=raw_target,
        command_rpm=command,
        saturated=saturated,
    )


class RpmRateLimiter:
    """Limit target RPM slew rate, starting and resetting at safe zero."""

    def __init__(self, max_rate_rpm_per_s: float) -> None:
        self.max_rate_rpm_per_s = _positive_real("max_rate_rpm_per_s", max_rate_rpm_per_s)
        self._last_timestamp: float | None = None
        self._last_output = 0.0

    @property
    def last_output(self) -> float:
        return self._last_output

    def reset(self) -> None:
        self._last_timestamp = None
        self._last_output = 0.0

    def update(self, target_rpm: float, timestamp: float) -> float:
        target = _finite_real("target_rpm", target_rpm)
        now = _finite_real("timestamp", timestamp)
        if self._last_timestamp is None:
            self._last_timestamp = now
            self._last_output = 0.0
            return self._last_output
        if now <= self._last_timestamp:
            raise ControlInputError("RPM 限速时间戳必须严格递增")
        max_change = self.max_rate_rpm_per_s * (now - self._last_timestamp)
        difference = target - self._last_output
        if difference > max_change:
            output = self._last_output + max_change
        elif difference < -max_change:
            output = self._last_output - max_change
        else:
            output = target
        self._last_timestamp = now
        self._last_output = output
        return output
