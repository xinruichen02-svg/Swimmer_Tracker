from __future__ import annotations

import queue

from vision_app.motor_backend import (
    MotorBackend,
    MotorBackendError,
    MotorFeedback,
    validate_target_rpm,
)
from vision_app.motor_link import MotorLink, MotorLinkError


class ArduinoSerialBackend(MotorBackend):
    name = "arduino_serial"
    is_real = True

    def __init__(self, port: str, *, link: MotorLink | None = None) -> None:
        self.port = port.strip() if isinstance(port, str) else ""
        self.link = link or MotorLink()

    @property
    def connected(self) -> bool:
        return self.link.connected

    def connect(self) -> None:
        if not self.port:
            raise MotorBackendError("Arduino 串口不能为空")
        try:
            self.link.connect(self.port)
        except MotorLinkError as exc:
            raise MotorBackendError(str(exc)) from exc

    def activate(self) -> None:
        try:
            self.link.send_target_rpm(0)
            self.link.send_start()
        except MotorLinkError as exc:
            raise MotorBackendError(str(exc)) from exc

    def set_target_rpm(self, rpm: int) -> None:
        try:
            self.link.send_target_rpm(validate_target_rpm(rpm))
        except MotorLinkError as exc:
            raise MotorBackendError(str(exc)) from exc

    def read_feedback(self, timeout: float = 0.0) -> MotorFeedback | None:
        try:
            event = self.link.events.get(timeout=max(0.0, timeout)) if timeout else self.link.events.get_nowait()
        except queue.Empty:
            return None
        if event.kind == "error":
            raise MotorBackendError(event.message)
        if event.telemetry is None:
            return None
        return MotorFeedback(event.telemetry.actual_rpm, event.telemetry.received_at)

    def stop(self, repeat: int = 5, interval_s: float = 0.01) -> None:
        del repeat, interval_s
        try:
            self.link.send_stop()
        except MotorLinkError as exc:
            raise MotorBackendError(str(exc)) from exc

    def close(self) -> None:
        self.link.disconnect(send_stop=True)

