from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class StateTransitionError(RuntimeError):
    """Raised when an unsafe application state transition is requested."""


class AppState(Enum):
    DISCONNECTED = auto()
    STOPPED = auto()
    CAMERA_READY = auto()
    TARGET_LOCKED = auto()
    RUNNING = auto()
    FAULT = auto()


@dataclass(frozen=True)
class SafetyInputs:
    serial_connected: bool = False
    telemetry_fresh: bool = False
    camera_ready: bool = False
    target_locked: bool = False
    calibration_confirmed: bool = False
    directions_valid: bool = False
    motion_solution_valid: bool = False
    offline_source: bool = False
    real_backend: bool = True

    def start_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.serial_connected:
            blockers.append("电机后端未连接")
        if not self.telemetry_fresh:
            blockers.append("尚未收到新鲜电机反馈")
        if not self.camera_ready:
            blockers.append("摄像头未就绪")
        if not self.target_locked:
            blockers.append("尚未框选并锁定运动员")
        if not self.calibration_confirmed:
            blockers.append("换算值尚未确认")
        if not self.directions_valid:
            blockers.append("方向配置无效")
        if not self.motion_solution_valid:
            blockers.append("运动解算尚未就绪")
        if self.offline_source and self.real_backend:
            blockers.append("离线视频禁止启动真实电机")
        return tuple(blockers)

    def constant_speed_blockers(self) -> tuple[str, ...]:
        """Requirements for fixed-speed motion, which intentionally ignores vision."""
        blockers: list[str] = []
        if not self.serial_connected:
            blockers.append("电机后端未连接")
        if not self.telemetry_fresh:
            blockers.append("尚未收到新鲜电机反馈")
        if not self.calibration_confirmed:
            blockers.append("换算值尚未确认")
        if not self.directions_valid:
            blockers.append("方向配置无效")
        return tuple(blockers)


class SafetyController:
    def __init__(self) -> None:
        self.state = AppState.DISCONNECTED
        self.fault_reason: str | None = None
        self._stop_requested = False

    def serial_connected(self) -> None:
        if self.state not in (AppState.DISCONNECTED, AppState.STOPPED):
            raise StateTransitionError(f"状态 {self.state.name} 下不能建立新串口连接")
        self.state = AppState.STOPPED
        self.fault_reason = None
        self._stop_requested = False

    def camera_opened(self) -> None:
        if self.state not in (AppState.STOPPED, AppState.CAMERA_READY, AppState.TARGET_LOCKED):
            raise StateTransitionError(f"状态 {self.state.name} 下不能打开摄像头")
        self.state = AppState.CAMERA_READY

    def camera_closed(self) -> None:
        if self.state is AppState.RUNNING:
            raise StateTransitionError("运行中摄像头关闭必须进入故障状态")
        if self.state in (AppState.CAMERA_READY, AppState.TARGET_LOCKED):
            self.state = AppState.STOPPED

    def target_locked(self) -> None:
        if self.state not in (AppState.CAMERA_READY, AppState.TARGET_LOCKED):
            raise StateTransitionError(f"状态 {self.state.name} 下不能锁定目标")
        self.state = AppState.TARGET_LOCKED

    def target_cleared(self) -> None:
        if self.state is AppState.RUNNING:
            raise StateTransitionError("运行中不能在未触发故障的情况下清除目标")
        if self.state in (AppState.CAMERA_READY, AppState.TARGET_LOCKED):
            self.state = AppState.CAMERA_READY

    def start(self, inputs: SafetyInputs) -> None:
        if self.state is not AppState.TARGET_LOCKED:
            raise StateTransitionError("只有目标已锁定状态才能启动闭环")
        blockers = inputs.start_blockers()
        if blockers:
            raise StateTransitionError("；".join(blockers))
        self.state = AppState.RUNNING
        self._stop_requested = False

    def start_constant_speed(self, inputs: SafetyInputs) -> None:
        if self.state not in (AppState.STOPPED, AppState.CAMERA_READY, AppState.TARGET_LOCKED):
            raise StateTransitionError("当前状态不能启动定速巡航")
        blockers = inputs.constant_speed_blockers()
        if blockers:
            raise StateTransitionError("；".join(blockers))
        self.state = AppState.RUNNING
        self._stop_requested = False

    def manual_stop(self) -> bool:
        if self.state is AppState.FAULT:
            self._stop_requested = True
            return True
        was_connected = self.state is not AppState.DISCONNECTED
        should_send_stop = self.state in (
            AppState.STOPPED,
            AppState.CAMERA_READY,
            AppState.TARGET_LOCKED,
            AppState.RUNNING,
            AppState.FAULT,
        )
        self.state = AppState.STOPPED if was_connected else AppState.DISCONNECTED
        self.fault_reason = None
        self._stop_requested = False
        return should_send_stop

    def fault(self, reason: str) -> bool:
        normalized = reason.strip() if isinstance(reason, str) else ""
        if not normalized:
            raise StateTransitionError("故障原因不能为空")
        if self.state is AppState.FAULT:
            return False
        self.state = AppState.FAULT
        self.fault_reason = normalized
        self._stop_requested = True
        return True

    def consume_stop_request(self) -> bool:
        if not self._stop_requested:
            return False
        self._stop_requested = False
        return True

    def acknowledge_fault(self) -> None:
        if self.state is not AppState.FAULT:
            raise StateTransitionError("当前没有可确认的故障")
        self.state = AppState.STOPPED
        self.fault_reason = None
        self._stop_requested = False

    def disconnected(self, reason: str | None = None) -> None:
        self.state = AppState.DISCONNECTED
        self.fault_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
        self._stop_requested = False
