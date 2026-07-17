from __future__ import annotations

import math
import time
from enum import Enum, auto

from vision_app.motor_backend import MotorBackend, MotorBackendError, MotorFeedback, validate_target_rpm
from vision_app.pid_compat import InoCompatiblePid, PidConfigurationError


class MotorControlError(RuntimeError):
    pass


class MotorControlMode(str, Enum):
    DRIVER_PID = "driver_pid"
    INO_PID_COMPAT = "ino_pid_compat"


class MotorControlState(Enum):
    DISCONNECTED = auto()
    CONNECTED_SAFE = auto()
    ARMED = auto()
    RUNNING = auto()
    FAULT = auto()


class PythonMotorController:
    def __init__(
        self,
        backend: MotorBackend,
        *,
        mode: MotorControlMode = MotorControlMode.DRIVER_PID,
        feedback_timeout_s: float = 0.5,
        pid: InoCompatiblePid | None = None,
    ) -> None:
        if not math.isfinite(feedback_timeout_s) or feedback_timeout_s <= 0.0:
            raise MotorControlError("反馈超时必须是正有限数")
        self.backend = backend
        self.mode = MotorControlMode(mode)
        self.feedback_timeout_s = feedback_timeout_s
        self.pid = pid or InoCompatiblePid()
        self.state = MotorControlState.DISCONNECTED
        self.target_rpm = 0
        self.last_output_rpm = 0
        self.last_feedback: MotorFeedback | None = None
        self.fault_reason: str | None = None
        self._last_tick: float | None = None

    def connect(self) -> None:
        if self.state is not MotorControlState.DISCONNECTED:
            raise MotorControlError("控制器已经连接")
        try:
            self.backend.connect()
            self.backend.activate()
        except Exception:
            self.backend.close()
            raise
        self.state = MotorControlState.CONNECTED_SAFE
        self.target_rpm = 0
        self.last_output_rpm = 0
        self.pid.reset()
        self._last_tick = None

    def poll_feedback(self, timeout: float = 0.0) -> MotorFeedback | None:
        feedback = self.backend.read_feedback(timeout)
        if feedback is not None:
            self.last_feedback = feedback
        return feedback

    def arm(self, now: float | None = None) -> None:
        if self.state is not MotorControlState.CONNECTED_SAFE:
            raise MotorControlError("只有安全连接状态可以解锁")
        timestamp = time.monotonic() if now is None else now
        feedback = self.last_feedback or self.poll_feedback(0.0)
        if feedback is None or timestamp - feedback.received_at > self.feedback_timeout_s:
            raise MotorControlError("没有新鲜电机反馈，禁止解锁")
        try:
            self.backend.start()
        except MotorBackendError as exc:
            self.fault(f"启动失败: {exc}")
            raise MotorControlError(f"启动失败: {exc}") from exc
        self.target_rpm = 0
        self.last_output_rpm = 0
        self.pid.reset()
        self._last_tick = timestamp
        self.state = MotorControlState.ARMED

    def set_target_rpm(self, rpm: int) -> None:
        if self.state not in (MotorControlState.ARMED, MotorControlState.RUNNING):
            raise MotorControlError("电机未解锁，不能设置非安全目标")
        self.target_rpm = validate_target_rpm(rpm)

    def tick(self, now: float | None = None) -> MotorFeedback | None:
        timestamp = time.monotonic() if now is None else now
        feedback = self.poll_feedback(0.0)
        if self.state not in (MotorControlState.ARMED, MotorControlState.RUNNING):
            return feedback
        latest = self.last_feedback
        if latest is None or max(0.0, timestamp - latest.received_at) > self.feedback_timeout_s:
            self.fault("电机反馈超时")
            return feedback
        dt = 0.01 if self._last_tick is None else max(0.001, min(0.1, timestamp - self._last_tick))
        self._last_tick = timestamp
        try:
            if self.mode is MotorControlMode.DRIVER_PID:
                output = self.target_rpm
            else:
                output = int(round(self.pid.update(self.target_rpm, latest.actual_rpm, dt)))
            self.backend.set_target_rpm(validate_target_rpm(output))
        except (MotorBackendError, PidConfigurationError) as exc:
            self.fault(f"控制输出失败: {exc}")
            return feedback
        self.last_output_rpm = output
        self.state = MotorControlState.RUNNING
        return feedback

    def stop(self) -> None:
        try:
            if self.backend.connected:
                self.backend.stop()
        finally:
            self.target_rpm = 0
            self.last_output_rpm = 0
            self.pid.reset()
            self._last_tick = None
            if self.state is not MotorControlState.DISCONNECTED:
                self.state = MotorControlState.CONNECTED_SAFE

    def fault(self, reason: str) -> None:
        normalized = reason.strip() if isinstance(reason, str) else ""
        if not normalized:
            normalized = "未知电机故障"
        try:
            if self.backend.connected:
                self.backend.stop()
        except MotorBackendError:
            pass
        self.target_rpm = 0
        self.last_output_rpm = 0
        self.pid.reset()
        self.fault_reason = normalized
        self.state = MotorControlState.FAULT

    def reset_fault(self) -> None:
        if self.state is not MotorControlState.FAULT:
            raise MotorControlError("当前没有电机故障")
        self.backend.stop()
        self.fault_reason = None
        self.last_feedback = None
        self.state = MotorControlState.CONNECTED_SAFE

    def close(self) -> None:
        try:
            if self.backend.connected:
                self.backend.stop()
        finally:
            self.backend.close()
            self.state = MotorControlState.DISCONNECTED
            self.target_rpm = 0
            self.last_output_rpm = 0
            self.pid.reset()
