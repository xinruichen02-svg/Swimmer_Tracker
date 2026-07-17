from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from vision_app.can_protocol import RPM_LIMIT


class MotorBackendError(RuntimeError):
    """Raised when a motor transport or device operation fails."""


@dataclass(frozen=True)
class MotorFeedback:
    actual_rpm: float
    received_at: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.actual_rpm) or not math.isfinite(self.received_at):
            raise MotorBackendError("电机反馈必须是有限数字")


class MotorBackend(ABC):
    name = "unknown"
    is_real = True

    @property
    @abstractmethod
    def connected(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def activate(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def start(self) -> None:
        """Explicitly enable motion after feedback and safety checks pass."""
        raise NotImplementedError

    @abstractmethod
    def set_target_rpm(self, rpm: int) -> None:
        raise NotImplementedError

    def set_pid_tunings(self, kp: float, ki: float, kd: float) -> None:
        """Apply controller gains when the selected backend supports online tuning."""
        del kp, ki, kd
        raise MotorBackendError(f"{self.name} 后端不支持在线 PID 调参")

    @abstractmethod
    def read_feedback(self, timeout: float = 0.0) -> MotorFeedback | None:
        raise NotImplementedError

    @abstractmethod
    def stop(self, repeat: int = 5, interval_s: float = 0.01) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


def validate_target_rpm(rpm: int) -> int:
    if isinstance(rpm, bool) or not isinstance(rpm, int):
        raise MotorBackendError("目标 RPM 必须是整数")
    if not -RPM_LIMIT <= rpm <= RPM_LIMIT:
        raise MotorBackendError(f"目标 RPM 必须位于 -{RPM_LIMIT}..{RPM_LIMIT}")
    return rpm


def repeat_stop(send_zero, repeat: int, interval_s: float) -> None:
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
        raise MotorBackendError("停车重复次数必须是正整数")
    if not math.isfinite(interval_s) or interval_s < 0.0:
        raise MotorBackendError("停车帧间隔必须是非负有限数")
    for index in range(repeat):
        send_zero()
        if interval_s and index + 1 < repeat:
            time.sleep(interval_s)
