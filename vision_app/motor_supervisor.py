from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from multiprocessing.connection import Connection

from vision_app.arduino_serial_backend import ArduinoSerialBackend
from vision_app.can_protocol import CAN_BITRATE
from vision_app.motor_backend import MotorBackend, MotorBackendError
from vision_app.python_can_backend import PythonCanBackend
from vision_app.python_motor_controller import (
    MotorControlMode,
    MotorControlState,
    PythonMotorController,
)
from vision_app.virtual_motor_backend import VirtualMotorBackend


@dataclass(frozen=True)
class BackendConfig:
    backend: str = "virtual"
    serial_port: str = ""
    can_interface: str = ""
    can_channel: str = ""
    can_bitrate: int = CAN_BITRATE
    control_mode: str = MotorControlMode.DRIVER_PID.value
    feedback_timeout_s: float = 0.5

    def validated(self) -> "BackendConfig":
        if self.backend not in ("virtual", "arduino_serial", "python_can"):
            raise MotorBackendError("后端必须是 virtual、arduino_serial 或 python_can")
        if self.backend == "arduino_serial" and not self.serial_port.strip():
            raise MotorBackendError("Arduino 串口不能为空")
        if self.backend == "python_can":
            if not self.can_interface.strip() or not self.can_channel.strip():
                raise MotorBackendError("真实 CAN 的 interface 和 channel 不能为空")
            if self.can_interface.strip().lower() == "virtual":
                raise MotorBackendError(
                    "真实 python_can 后端不能使用 virtual interface"
                )
        if (
            isinstance(self.can_bitrate, bool)
            or not isinstance(self.can_bitrate, int)
            or self.can_bitrate <= 0
        ):
            raise MotorBackendError("CAN 波特率必须是正整数")
        MotorControlMode(self.control_mode)
        if not math.isfinite(self.feedback_timeout_s) or self.feedback_timeout_s <= 0.0:
            raise MotorBackendError("反馈超时必须是正有限数")
        return self


def build_backend(config: BackendConfig) -> MotorBackend:
    config.validated()
    if config.backend == "virtual":
        return VirtualMotorBackend()
    if config.backend == "arduino_serial":
        return ArduinoSerialBackend(config.serial_port)
    return PythonCanBackend(
        interface=config.can_interface,
        channel=config.can_channel,
        bitrate=config.can_bitrate,
    )


def _send(connection: Connection, kind: str, **payload) -> bool:
    try:
        connection.send({"kind": kind, **payload})
        return True
    except (BrokenPipeError, EOFError, OSError):
        return False


def _status(
    controller: PythonMotorController,
    config: BackendConfig,
    *,
    stop_confirmed: bool = False,
) -> dict:
    feedback = controller.last_feedback
    return {
        "state": controller.state.name,
        "backend": config.backend,
        "is_real": controller.backend.is_real,
        "target_rpm": controller.target_rpm,
        "output_rpm": controller.last_output_rpm,
        "actual_rpm": None if feedback is None else feedback.actual_rpm,
        "feedback_at": None if feedback is None else feedback.received_at,
        "fault": controller.fault_reason,
        "stop_confirmed": stop_confirmed,
    }


def _confirm_stop(
    controller: PythonMotorController,
    timeout_s: float = 1.0,
    tolerance_rpm: float = 5.0,
) -> bool:
    controller.stop()
    consecutive = 0
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        feedback = controller.poll_feedback(0.05)
        if feedback is None:
            continue
        if abs(feedback.actual_rpm) <= tolerance_rpm:
            consecutive += 1
            if consecutive >= 3:
                return True
        else:
            consecutive = 0
    return False


def supervisor_process(
    connection: Connection,
    config: BackendConfig,
    heartbeat_timeout_s: float = 0.5,
    target_timeout_s: float = 0.5,
) -> None:
    controller: PythonMotorController | None = None
    try:
        config.validated()
        controller = PythonMotorController(
            build_backend(config),
            mode=MotorControlMode(config.control_mode),
            feedback_timeout_s=config.feedback_timeout_s,
        )
        controller.connect()
        deadline = time.monotonic() + 2.0
        while controller.last_feedback is None and time.monotonic() < deadline:
            controller.poll_feedback(0.05)
        if controller.last_feedback is None:
            raise MotorBackendError("连接后 2 秒内没有收到电机反馈")
        if not _send(
            connection,
            "READY",
            config=asdict(config),
            status=_status(controller, config),
        ):
            return

        last_heartbeat = time.monotonic()
        last_target_at: float | None = None
        last_sequence = -1
        pending_target = 0
        next_tick = time.monotonic()
        next_status = next_tick
        next_fault_stop = next_tick
        stop_confirmed = False

        while True:
            now = time.monotonic()
            while connection.poll(0.0):
                try:
                    message = connection.recv()
                except (EOFError, OSError):
                    _confirm_stop(controller)
                    return
                if not isinstance(message, dict):
                    continue
                kind = message.get("kind")
                sequence = message.get("sequence", -1)
                sent_at = message.get("sent_at", now)
                if kind in ("HEARTBEAT", "TARGET"):
                    if (
                        isinstance(sequence, bool)
                        or not isinstance(sequence, int)
                        or sequence <= last_sequence
                    ):
                        continue
                    if (
                        not isinstance(sent_at, (int, float))
                        or isinstance(sent_at, bool)
                        or not math.isfinite(sent_at)
                    ):
                        continue
                    if sent_at > now + 0.2 or now - sent_at > heartbeat_timeout_s:
                        continue
                    last_sequence = sequence
                if kind == "HEARTBEAT":
                    last_heartbeat = now
                elif kind == "TARGET":
                    target = message.get("rpm")
                    if (
                        isinstance(target, bool)
                        or not isinstance(target, int)
                        or not -2047 <= target <= 2047
                    ):
                        controller.fault("收到非法目标 RPM")
                    else:
                        pending_target = target
                        last_target_at = now
                        if controller.state in (
                            MotorControlState.ARMED,
                            MotorControlState.RUNNING,
                        ):
                            controller.set_target_rpm(target)
                elif kind == "ARM":
                    try:
                        controller.arm(now)
                        controller.set_target_rpm(pending_target)
                        last_target_at = now
                        stop_confirmed = False
                    except Exception as exc:
                        controller.fault(f"解锁失败: {exc}")
                elif kind == "STOP":
                    stop_confirmed = _confirm_stop(controller)
                    _send(
                        connection,
                        "STOPPED",
                        status=_status(
                            controller, config, stop_confirmed=stop_confirmed
                        ),
                    )
                elif kind == "RESET":
                    try:
                        controller.reset_fault()
                        controller.poll_feedback(0.1)
                    except Exception as exc:
                        controller.fault(f"故障复位失败: {exc}")
                elif kind == "SHUTDOWN":
                    stop_confirmed = _confirm_stop(controller)
                    _send(
                        connection,
                        "CLOSED",
                        status=_status(
                            controller, config, stop_confirmed=stop_confirmed
                        ),
                    )
                    return

            now = time.monotonic()
            active = controller.state in (
                MotorControlState.ARMED,
                MotorControlState.RUNNING,
            )
            if active and now - last_heartbeat > heartbeat_timeout_s:
                controller.fault("GUI 心跳超过 500 ms")
            elif active and (
                last_target_at is None or now - last_target_at > target_timeout_s
            ):
                controller.fault("目标命令超过 500 ms 未更新")

            if now >= next_tick:
                controller.tick(now)
                next_tick = now + 0.01
            if controller.state is MotorControlState.FAULT and now >= next_fault_stop:
                try:
                    controller.backend.stop()
                except MotorBackendError:
                    pass
                next_fault_stop = now + 0.1
            if now >= next_status:
                if not _send(
                    connection,
                    "STATUS",
                    status=_status(controller, config, stop_confirmed=stop_confirmed),
                ):
                    _confirm_stop(controller)
                    return
                next_status = now + 0.05
            time.sleep(0.002)
    except Exception as exc:
        if controller is not None:
            try:
                controller.fault(str(exc))
            except Exception:
                pass
        _send(connection, "ERROR", message=str(exc))
    finally:
        if controller is not None:
            try:
                controller.close()
            except Exception:
                pass
        try:
            connection.close()
        except Exception:
            pass
