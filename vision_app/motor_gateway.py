from __future__ import annotations

import math
import time

from vision_app.control_core import ControlInputError, RpmRateLimiter
from vision_app.motor_backend import validate_target_rpm
from vision_app.motor_supervisor import BackendConfig
from vision_app.supervisor_client import MotorSupervisorClient


class MotorCommandGateway:
    """Layer 1: the GUI-facing motor command and unit-conversion boundary."""

    def __init__(self, client: MotorSupervisorClient | None = None) -> None:
        self.client = client or MotorSupervisorClient()
        self._limiter = RpmRateLimiter(500.0)
        self.commanded_rpm_estimate = 0

    @property
    def connected(self) -> bool:
        return self.client.connected

    @property
    def is_real(self) -> bool:
        return self.client.is_real

    @property
    def events(self):
        return self.client.events

    @property
    def last_status(self) -> dict:
        return self.client.last_status

    def connect(self, config: BackendConfig) -> None:
        self.client.connect(config)
        self.reset_rate_limit()

    def start(self) -> None:
        self.client.send_target_rpm(0)
        self.client.send_start()
        self.commanded_rpm_estimate = 0

    def configure_rate_limit(self, max_rate_rpm_per_s: float) -> None:
        self._limiter = RpmRateLimiter(max_rate_rpm_per_s)

    def reset_rate_limit(self) -> None:
        self._limiter.reset()
        self.commanded_rpm_estimate = 0

    def set_expected_rpm(self, rpm: float, rpm_limit: int, timestamp: float | None = None) -> int:
        if isinstance(rpm, bool) or not isinstance(rpm, (int, float)) or not math.isfinite(rpm):
            raise ControlInputError("期望 RPM 必须是有限数字")
        if not 1 <= rpm_limit <= 2047:
            raise ControlInputError("RPM 上限必须位于 1..2047")
        target = max(-rpm_limit, min(rpm_limit, float(rpm)))
        limited = self._limiter.update(target, time.monotonic() if timestamp is None else timestamp)
        command = max(-rpm_limit, min(rpm_limit, int(round(limited))))
        validate_target_rpm(command)
        self.client.send_target_rpm(command)
        self.commanded_rpm_estimate = command
        return command

    def set_expected_speed(
        self,
        speed_mps: float,
        rpm_per_mps: float,
        motor_axis_sign: int,
        rpm_limit: int,
        timestamp: float | None = None,
    ) -> tuple[float, int]:
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (speed_mps, rpm_per_mps)):
            raise ControlInputError("线速度和换算比例必须是有效数字")
        if not math.isfinite(speed_mps) or not math.isfinite(rpm_per_mps) or rpm_per_mps <= 0:
            raise ControlInputError("线速度和换算比例必须是有效数字")
        if motor_axis_sign not in (-1, 1):
            raise ControlInputError("电机方向只能是 -1 或 +1")
        raw_rpm = motor_axis_sign * speed_mps * rpm_per_mps
        return raw_rpm, self.set_expected_rpm(raw_rpm, rpm_limit, timestamp)

    def estimated_speed_mps(self, rpm_per_mps: float, motor_axis_sign: int) -> float:
        if isinstance(rpm_per_mps, bool) or not isinstance(rpm_per_mps, (int, float)) or not math.isfinite(rpm_per_mps) or rpm_per_mps <= 0 or motor_axis_sign not in (-1, 1):
            raise ControlInputError("速度估算参数无效")
        return motor_axis_sign * self.commanded_rpm_estimate / rpm_per_mps

    def stop(self) -> None:
        self.client.send_stop()
        self.reset_rate_limit()

    def reset_fault(self) -> None:
        self.client.reset_fault()
        self.reset_rate_limit()

    def close(self) -> bool:
        result = self.client.disconnect(send_stop=True)
        self.reset_rate_limit()
        return result
