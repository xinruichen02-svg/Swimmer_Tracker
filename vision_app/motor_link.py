from __future__ import annotations

import math
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any


SERIAL_BAUD_RATE = 115200
PROTOCOL_RPM_LIMIT = 2047


class MotorProtocolError(ValueError):
    """Raised when a serial command or telemetry value is invalid."""


class MotorLinkError(RuntimeError):
    """Raised when the physical serial link cannot be used."""


def encode_start() -> bytes:
    return b"S\n"


def encode_stop() -> bytes:
    return b"P\n"


def encode_target_rpm(rpm: int) -> bytes:
    if isinstance(rpm, bool) or not isinstance(rpm, int):
        raise MotorProtocolError("目标 RPM 必须是整数")
    if not -PROTOCOL_RPM_LIMIT <= rpm <= PROTOCOL_RPM_LIMIT:
        raise MotorProtocolError("目标 RPM 超出 INO 协议范围 -2047..2047")
    return f"T{rpm}\n".encode("ascii")


@dataclass(frozen=True)
class MotorTelemetry:
    target_rpm: float
    actual_rpm: float
    output_rpm: float
    received_at: float


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_TELEMETRY_PATTERN = re.compile(
    rf"^\s*目标:\s*(?P<target>{_NUMBER})\s*,\s*"
    rf"实际:\s*(?P<actual>{_NUMBER})\s*,\s*"
    rf"输出:\s*(?P<output>{_NUMBER})\s*$"
)


class TelemetryParser:
    def __init__(self, max_buffer_bytes: int = 8192) -> None:
        if isinstance(max_buffer_bytes, bool) or not isinstance(max_buffer_bytes, int) or max_buffer_bytes < 256:
            raise MotorProtocolError("max_buffer_bytes 必须是至少 256 的整数")
        self.max_buffer_bytes = max_buffer_bytes
        self._buffer = bytearray()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes, received_at: float) -> list[MotorTelemetry]:
        if not isinstance(data, bytes):
            raise MotorProtocolError("串口输入必须是 bytes")
        if isinstance(received_at, bool) or not isinstance(received_at, (int, float)):
            raise MotorProtocolError("接收时间必须是数字")
        timestamp = float(received_at)
        if not math.isfinite(timestamp):
            raise MotorProtocolError("接收时间必须是有限数字")

        self._buffer.extend(data)
        if len(self._buffer) > self.max_buffer_bytes and b"\n" not in self._buffer:
            self._buffer.clear()
            return []

        telemetry_events: list[MotorTelemetry] = []
        while True:
            newline_index = self._buffer.find(b"\n")
            if newline_index < 0:
                break
            raw_line = bytes(self._buffer[:newline_index])
            del self._buffer[: newline_index + 1]
            line = raw_line.decode("utf-8", errors="replace").strip()
            match = _TELEMETRY_PATTERN.fullmatch(line)
            if match is None:
                continue
            values = tuple(float(match.group(name)) for name in ("target", "actual", "output"))
            if not all(math.isfinite(value) for value in values):
                continue
            telemetry_events.append(
                MotorTelemetry(
                    target_rpm=values[0],
                    actual_rpm=values[1],
                    output_rpm=values[2],
                    received_at=timestamp,
                )
            )
        return telemetry_events


@dataclass(frozen=True)
class MotorLinkEvent:
    kind: str
    message: str
    received_at: float
    telemetry: MotorTelemetry | None = None


class MotorLink:
    """Threaded serial transport. GUI consumers poll ``events`` on the main thread."""

    def __init__(self, serial_factory=None) -> None:
        self.events: queue.Queue[MotorLinkEvent] = queue.Queue()
        self._serial_factory = serial_factory
        self._serial: Any | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self._write_lock = threading.Lock()
        self._parser = TelemetryParser()

    @property
    def connected(self) -> bool:
        serial_port = self._serial
        return bool(serial_port is not None and getattr(serial_port, "is_open", False))

    def connect(self, port: str) -> None:
        port_name = port.strip() if isinstance(port, str) else ""
        if not port_name:
            raise MotorLinkError("串口名称不能为空")
        if self.connected:
            raise MotorLinkError("串口已经连接")
        self._clear_events()
        serial_factory = self._serial_factory
        if serial_factory is None:
            try:
                import serial  # type: ignore
            except ImportError as exc:
                raise MotorLinkError("缺少 pyserial，请先安装 requirements.txt 中的依赖") from exc
            serial_factory = serial.Serial

        try:
            serial_port = serial_factory(
                port=port_name,
                baudrate=SERIAL_BAUD_RATE,
                timeout=0.10,
                write_timeout=0.20,
            )
        except Exception as exc:
            raise MotorLinkError(f"无法打开串口 {port_name}: {exc}") from exc

        self._serial = serial_port
        self._parser.reset()
        self._stop_reader.clear()
        try:
            self.send_stop()
        except Exception:
            serial_port.close()
            self._serial = None
            raise
        self._reader_thread = threading.Thread(target=self._reader_loop, name="motor-serial-reader", daemon=True)
        self._reader_thread.start()

    def _send(self, payload: bytes) -> None:
        serial_port = self._serial
        if serial_port is None or not getattr(serial_port, "is_open", False):
            raise MotorLinkError("串口未连接")
        try:
            with self._write_lock:
                written = serial_port.write(payload)
                serial_port.flush()
        except Exception as exc:
            raise MotorLinkError(f"串口发送失败: {exc}") from exc
        if written != len(payload):
            raise MotorLinkError("串口未完整写入控制命令")

    def send_start(self) -> None:
        self._send(encode_start())

    def send_stop(self) -> None:
        self._send(encode_stop())

    def send_target_rpm(self, rpm: int) -> None:
        self._send(encode_target_rpm(rpm))

    def _reader_loop(self) -> None:
        while not self._stop_reader.is_set():
            serial_port = self._serial
            if serial_port is None:
                return
            try:
                data = serial_port.read(256)
                if not data:
                    continue
                now = time.monotonic()
                for telemetry in self._parser.feed(data, now):
                    self.events.put(
                        MotorLinkEvent(
                            kind="telemetry",
                            message="收到电机反馈",
                            received_at=now,
                            telemetry=telemetry,
                        )
                    )
            except Exception as exc:
                if self._stop_reader.is_set():
                    return
                now = time.monotonic()
                self.events.put(
                    MotorLinkEvent(
                        kind="error",
                        message=f"串口读取失败: {exc}",
                        received_at=now,
                    )
                )
                return

    def disconnect(self, *, send_stop: bool = True) -> bool:
        stop_sent = False
        if send_stop and self.connected:
            try:
                self.send_stop()
                stop_sent = True
            except MotorLinkError:
                stop_sent = False
        self._stop_reader.set()
        serial_port = self._serial
        self._serial = None
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception:
                pass
        reader = self._reader_thread
        self._reader_thread = None
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=0.5)
        self._parser.reset()
        self._clear_events()
        return stop_sent

    def _clear_events(self) -> None:
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                return
