from __future__ import annotations

import math


class PidConfigurationError(ValueError):
    pass


class InoCompatiblePid:
    """Discrete PID with derivative-on-measurement and back-calculation anti-windup."""

    def __init__(
        self,
        kp: float = 1.0,
        ki: float = 0.05,
        kd: float = 0.02,
        *,
        output_min: float = -2047.0,
        output_max: float = 2047.0,
        anti_windup_gain: float = 1.0,
    ) -> None:
        values = (kp, ki, kd, output_min, output_max, anti_windup_gain)
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in values
        ):
            raise PidConfigurationError("PID 参数必须是有限数字")
        if kp < 0 or ki < 0 or kd < 0 or anti_windup_gain < 0:
            raise PidConfigurationError("PID 参数不能为负数")
        if output_min >= output_max:
            raise PidConfigurationError("PID 输出下限必须小于上限")
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)
        self.output_min = float(output_min)
        self.output_max = float(output_max)
        self.anti_windup_gain = float(anti_windup_gain)
        self._integral = 0.0
        self._previous_input: float | None = None

    def reset(self) -> None:
        self._integral = 0.0
        self._previous_input = None

    def update(self, setpoint: float, actual: float, dt: float) -> float:
        values = (setpoint, actual, dt)
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in values
        ):
            raise PidConfigurationError("PID 输入和周期必须是有限数字")
        if dt <= 0.0:
            raise PidConfigurationError("PID 周期必须大于 0")
        error = float(setpoint) - float(actual)
        derivative = (
            0.0
            if self._previous_input is None
            else -(float(actual) - self._previous_input) / dt
        )
        provisional_integral = self._integral + self.ki * error * dt
        unsaturated = self.kp * error + provisional_integral + self.kd * derivative
        saturated = max(self.output_min, min(self.output_max, unsaturated))
        self._integral = (
            provisional_integral
            + self.anti_windup_gain * (saturated - unsaturated) * dt
        )
        self._previous_input = float(actual)
        return saturated
