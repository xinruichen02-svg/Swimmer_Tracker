from __future__ import annotations

import queue
import socket
import threading
import time

from vision_app.motor_backend import (
    MotorBackend,
    MotorBackendError,
    MotorFeedback,
    repeat_stop,
    validate_target_rpm,
)
from vision_app.motor_link import encode_start, encode_stop, encode_target_rpm


class TcpMotorBackend(MotorBackend):
    """TCP transport for the unchanged S/P/T line protocol."""

    name = "tcp"
    is_real = True
    supports_feedback = False

    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_timeout_s: float = 5.0,
        socket_factory=None,
    ) -> None:
        self.host = host.strip() if isinstance(host, str) else ""
        self.port = port
        self.connect_timeout_s = connect_timeout_s
        self._socket_factory = socket_factory or socket.create_connection
        self._socket = None
        self._send_lock = threading.Lock()
        self._reader_stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._errors: queue.Queue[str] = queue.Queue()
        self._fault: str | None = None
        self._raw_lines: queue.Queue[str] = queue.Queue(maxsize=100)
        self._receive_buffer = bytearray()

    @property
    def connected(self) -> bool:
        return self._socket is not None and self._fault is None

    @property
    def raw_lines(self) -> queue.Queue[str]:
        return self._raw_lines

    def connect(self) -> None:
        if not self.host:
            raise MotorBackendError("TCP 主机地址不能为空")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise MotorBackendError("TCP 端口必须位于 1..65535")
        if self._socket is not None:
            raise MotorBackendError("TCP 电机后端已经连接")
        self._clear_queue(self._errors)
        self._fault = None
        self._clear_queue(self._raw_lines)
        try:
            sock = self._socket_factory((self.host, self.port), timeout=self.connect_timeout_s)
            sock.settimeout(0.2)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError:
                pass
        except Exception as exc:
            raise MotorBackendError(f"无法连接 TCP 电机 {self.host}:{self.port}: {exc}") from exc
        self._socket = sock
        self._reader_stop.clear()
        self._reader = threading.Thread(target=self._reader_loop, name="motor-tcp-reader", daemon=True)
        self._reader.start()

    def activate(self) -> None:
        self._send(encode_stop())
        self._send(encode_target_rpm(0))

    def start(self) -> None:
        self._send(encode_target_rpm(0))
        self._send(encode_start())

    def set_target_rpm(self, rpm: int) -> None:
        self._send(encode_target_rpm(validate_target_rpm(rpm)))

    def read_feedback(self, timeout: float = 0.0) -> MotorFeedback | None:
        del timeout
        try:
            message = self._errors.get_nowait()
        except queue.Empty:
            return None
        raise MotorBackendError(message)

    def stop(self, repeat: int = 5, interval_s: float = 0.01) -> None:
        repeat_stop(lambda: self._send(encode_stop(), allow_fault=True), repeat, interval_s)

    def close(self) -> None:
        sock = self._socket
        if sock is not None:
            try:
                self.stop(repeat=3, interval_s=0.01)
            except MotorBackendError:
                pass
        self._reader_stop.set()
        self._socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        reader = self._reader
        self._reader = None
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=0.5)
        self._receive_buffer.clear()

    def _send(self, payload: bytes, *, allow_fault: bool = False) -> None:
        sock = self._socket
        if sock is None:
            raise MotorBackendError("TCP 电机后端未连接")
        if not allow_fault:
            self._raise_pending_error()
        try:
            with self._send_lock:
                sock.sendall(payload)
        except Exception as exc:
            self._record_error(f"TCP 电机命令发送失败: {exc}")
            raise MotorBackendError(f"TCP 电机命令发送失败: {exc}") from exc

    def _reader_loop(self) -> None:
        while not self._reader_stop.is_set():
            sock = self._socket
            if sock is None:
                return
            try:
                data = sock.recv(4096)
                if not data:
                    self._record_error("TCP 电机连接已由服务端关闭")
                    return
                self._receive_buffer.extend(data)
                while b"\n" in self._receive_buffer:
                    raw, _, remainder = self._receive_buffer.partition(b"\n")
                    self._receive_buffer = bytearray(remainder)
                    self._put_raw(raw.decode("utf-8", errors="replace").strip())
            except socket.timeout:
                continue
            except Exception as exc:
                if not self._reader_stop.is_set():
                    self._record_error(f"TCP 电机接收失败: {exc}")
                return

    def _record_error(self, message: str) -> None:
        if self._fault is None:
            self._fault = message
            self._errors.put(message)

    def _raise_pending_error(self) -> None:
        if self._fault is not None:
            raise MotorBackendError(self._fault)

    def _put_raw(self, line: str) -> None:
        if not line:
            return
        if self._raw_lines.full():
            try:
                self._raw_lines.get_nowait()
            except queue.Empty:
                pass
        self._raw_lines.put(line)

    @staticmethod
    def _clear_queue(target: queue.Queue) -> None:
        while True:
            try:
                target.get_nowait()
            except queue.Empty:
                return
