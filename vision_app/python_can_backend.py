from __future__ import annotations

import time
from typing import Any

from vision_app.can_protocol import (
    CAN_BITRATE,
    CanFrame,
    CanProtocolError,
    decode_speed_feedback,
    encode_activate,
    encode_speed_command,
)
from vision_app.motor_backend import (
    MotorBackend,
    MotorBackendError,
    MotorFeedback,
    repeat_stop,
    validate_target_rpm,
)


class PythonCanBackend(MotorBackend):
    name = "python_can"
    is_real = True

    def __init__(
        self,
        *,
        interface: str,
        channel: str | int,
        bitrate: int = CAN_BITRATE,
        bus_factory=None,
        bus_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.interface = interface.strip() if isinstance(interface, str) else ""
        self.channel = channel
        self.bitrate = bitrate
        self._bus_factory = bus_factory
        self._bus_kwargs = dict(bus_kwargs or {})
        self._bus = None

    @property
    def connected(self) -> bool:
        return self._bus is not None

    def connect(self) -> None:
        if self.connected:
            raise MotorBackendError("CAN 后端已经连接")
        if not self.interface:
            raise MotorBackendError("python-can interface 不能为空")
        if self.channel is None or (
            isinstance(self.channel, str) and not self.channel.strip()
        ):
            raise MotorBackendError("python-can channel 不能为空")
        if (
            isinstance(self.bitrate, bool)
            or not isinstance(self.bitrate, int)
            or self.bitrate <= 0
        ):
            raise MotorBackendError("CAN 波特率必须是正整数")
        try:
            import can
        except ImportError as exc:
            raise MotorBackendError(
                "缺少 python-can，请先安装 requirements.txt"
            ) from exc
        factory = self._bus_factory or can.Bus
        kwargs = dict(self._bus_kwargs)
        kwargs.update(interface=self.interface, channel=self.channel)
        if self.interface != "virtual":
            kwargs["bitrate"] = self.bitrate
        try:
            self._bus = factory(**kwargs)
        except Exception as exc:
            raise MotorBackendError(
                f"无法打开 CAN 后端 interface={self.interface!r}, channel={self.channel!r}: {exc}"
            ) from exc

    def _send_frame(self, frame: CanFrame) -> None:
        bus = self._bus
        if bus is None:
            raise MotorBackendError("CAN 后端未连接")
        try:
            import can

            bus.send(
                can.Message(
                    arbitration_id=frame.arbitration_id,
                    data=frame.data,
                    is_extended_id=frame.is_extended_id,
                ),
                timeout=0.2,
            )
        except Exception as exc:
            raise MotorBackendError(f"CAN 发送失败: {exc}") from exc

    def activate(self) -> None:
        self._send_frame(encode_activate())
        self.stop(repeat=3)

    def start(self) -> None:
        # Direct CAN backends are activated during connect; motion begins only
        # when the controller sends a non-zero target after arming.
        return None

    def set_target_rpm(self, rpm: int) -> None:
        self._send_frame(encode_speed_command(validate_target_rpm(rpm)))

    def read_feedback(self, timeout: float = 0.0) -> MotorFeedback | None:
        bus = self._bus
        if bus is None:
            raise MotorBackendError("CAN 后端未连接")
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = max(0.0, deadline - time.monotonic()) if timeout else 0.0
            try:
                message = bus.recv(timeout=remaining)
            except Exception as exc:
                raise MotorBackendError(f"CAN 接收失败: {exc}") from exc
            if message is None:
                return None
            try:
                frame = CanFrame(
                    arbitration_id=int(message.arbitration_id),
                    data=bytes(message.data),
                    is_extended_id=bool(message.is_extended_id),
                )
                actual = decode_speed_feedback(frame)
            except CanProtocolError:
                if timeout and time.monotonic() < deadline:
                    continue
                return None
            return MotorFeedback(float(actual), time.monotonic())

    def stop(self, repeat: int = 5, interval_s: float = 0.01) -> None:
        repeat_stop(lambda: self.set_target_rpm(0), repeat, interval_s)

    def close(self) -> None:
        bus = self._bus
        self._bus = None
        if bus is not None:
            try:
                bus.shutdown()
            except Exception:
                pass
