from __future__ import annotations

import threading
import time
import uuid

from vision_app.can_protocol import (
    ACTIVATE_COMMAND_ID,
    CanFrame,
    CanProtocolError,
    decode_speed_command,
    encode_speed_feedback,
)
from vision_app.motor_backend import MotorBackendError


class SimulatedMotor:
    """A protocol-level motor node used only on python-can's virtual bus."""

    def __init__(self, channel: str | None = None, *, update_interval_s: float = 0.01) -> None:
        self.channel = channel or f"swimmer-{uuid.uuid4().hex}"
        self.update_interval_s = update_interval_s
        self.target_rpm = 0
        self.actual_rpm = 0.0
        self.activated = False
        self._bus = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            raise MotorBackendError("虚拟电机已经启动")
        try:
            import can
        except ImportError as exc:
            raise MotorBackendError("缺少 python-can，无法启动虚拟电机") from exc
        self._bus = can.Bus(interface="virtual", channel=self.channel, receive_own_messages=False)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="simulated-motor", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        last = time.monotonic()
        next_feedback = last
        while not self._stop.is_set():
            bus = self._bus
            if bus is None:
                return
            message = bus.recv(timeout=self.update_interval_s)
            if message is not None:
                try:
                    frame = CanFrame(
                        int(message.arbitration_id),
                        bytes(message.data),
                        bool(message.is_extended_id),
                    )
                    if frame.arbitration_id == ACTIVATE_COMMAND_ID:
                        self.activated = True
                    else:
                        self.target_rpm = decode_speed_command(frame) if self.activated else 0
                except CanProtocolError:
                    pass
            now = time.monotonic()
            dt = max(0.0, now - last)
            last = now
            desired = float(self.target_rpm if self.activated else 0)
            max_step = 5000.0 * dt
            delta = max(-max_step, min(max_step, desired - self.actual_rpm))
            self.actual_rpm += delta
            if now >= next_feedback:
                frame = encode_speed_feedback(int(round(self.actual_rpm)))
                try:
                    import can

                    bus.send(
                        can.Message(
                            arbitration_id=frame.arbitration_id,
                            data=frame.data,
                            is_extended_id=False,
                        )
                    )
                except Exception:
                    return
                next_feedback = now + 0.02

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=1.0)
        bus = self._bus
        self._bus = None
        if bus is not None:
            try:
                bus.shutdown()
            except Exception:
                pass

