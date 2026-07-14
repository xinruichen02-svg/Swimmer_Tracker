from __future__ import annotations

import multiprocessing
import queue
import threading
import time

from vision_app.motor_link import MotorLinkEvent, MotorTelemetry
from vision_app.motor_supervisor import BackendConfig, supervisor_process


class SupervisorClientError(RuntimeError):
    pass


class MotorSupervisorClient:
    """GUI-side API. The child process is the only owner of a motor backend."""

    def __init__(self) -> None:
        self.events: queue.Queue[MotorLinkEvent] = queue.Queue()
        self._connection = None
        self._process = None
        self._monitor: threading.Thread | None = None
        self._heartbeat: threading.Thread | None = None
        self._stop_threads = threading.Event()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._send_lock = threading.Lock()
        self._sequence = 0
        self._connected = False
        self._startup_error: str | None = None
        self.config: BackendConfig | None = None
        self.last_status: dict = {}
        self._reported_fault: str | None = None

    @property
    def connected(self) -> bool:
        process = self._process
        return bool(self._connected and process is not None and process.is_alive())

    @property
    def is_real(self) -> bool:
        return bool(self.config is not None and self.config.backend != "virtual")

    def connect(self, config: BackendConfig, timeout_s: float = 4.0) -> None:
        if self._process is not None:
            raise SupervisorClientError("电机监督进程已经启动")
        config.validated()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=supervisor_process,
            args=(child, config),
            name="swimmer-motor-supervisor",
        )
        self.config = config
        self._connection = parent
        self._process = process
        self._ready.clear()
        self._closed.clear()
        self._stop_threads.clear()
        self._startup_error = None
        self._reported_fault = None
        process.start()
        child.close()
        self._monitor = threading.Thread(target=self._monitor_loop, name="supervisor-monitor", daemon=True)
        self._monitor.start()
        self._heartbeat = threading.Thread(target=self._heartbeat_loop, name="supervisor-heartbeat", daemon=True)
        self._heartbeat.start()
        if not self._ready.wait(timeout_s):
            error = self._startup_error or "电机监督进程启动超时"
            self.disconnect(send_stop=True)
            raise SupervisorClientError(error)
        if self._startup_error:
            error = self._startup_error
            self.disconnect(send_stop=True)
            raise SupervisorClientError(error)

    def _next_envelope(self, kind: str, **payload) -> dict:
        self._sequence += 1
        return {
            "kind": kind,
            "sequence": self._sequence,
            "sent_at": time.monotonic(),
            **payload,
        }

    def _send(self, kind: str, **payload) -> None:
        connection = self._connection
        if connection is None:
            raise SupervisorClientError("监督进程未连接")
        try:
            with self._send_lock:
                connection.send(self._next_envelope(kind, **payload))
        except (BrokenPipeError, EOFError, OSError) as exc:
            self._connected = False
            raise SupervisorClientError(f"监督进程通信失败: {exc}") from exc

    def _heartbeat_loop(self) -> None:
        while not self._stop_threads.wait(0.1):
            if self._connection is None:
                return
            try:
                self._send("HEARTBEAT")
            except SupervisorClientError:
                return

    def _monitor_loop(self) -> None:
        connection = self._connection
        if connection is None:
            return
        while not self._stop_threads.is_set():
            try:
                if not connection.poll(0.1):
                    continue
                message = connection.recv()
            except (EOFError, OSError):
                self._connected = False
                self._closed.set()
                return
            kind = message.get("kind") if isinstance(message, dict) else None
            now = time.monotonic()
            if kind in ("READY", "STATUS", "STOPPED", "CLOSED"):
                status = message.get("status") or {}
                self.last_status = status
                actual = status.get("actual_rpm")
                feedback_at = status.get("feedback_at")
                if actual is not None and feedback_at is not None:
                    self.events.put(
                        MotorLinkEvent(
                            "telemetry",
                            "收到监督进程电机反馈",
                            now,
                            MotorTelemetry(
                                float(status.get("target_rpm", 0)),
                                float(actual),
                                float(status.get("output_rpm", 0)),
                                float(feedback_at),
                            ),
                        )
                    )
                self.events.put(MotorLinkEvent("status", str(status.get("state", "")), now))
                if kind == "READY":
                    self._connected = True
                    self._ready.set()
                if kind == "CLOSED":
                    self._connected = False
                    self._closed.set()
                fault = status.get("fault")
                if fault and fault != self._reported_fault:
                    self._reported_fault = str(fault)
                    self.events.put(MotorLinkEvent("error", str(fault), now))
                elif not fault:
                    self._reported_fault = None
            elif kind == "ERROR":
                self._startup_error = str(message.get("message") or "监督进程未知错误")
                self.events.put(MotorLinkEvent("error", self._startup_error, now))
                self._ready.set()

    def send_target_rpm(self, rpm: int) -> None:
        self._send("TARGET", rpm=rpm)

    def send_start(self) -> None:
        self._send("ARM")

    def send_stop(self) -> None:
        self._send("STOP")

    def reset_fault(self) -> None:
        self._send("RESET")

    def disconnect(self, *, send_stop: bool = True) -> bool:
        process = self._process
        if process is None:
            return False
        stop_requested = False
        try:
            if send_stop and process.is_alive():
                self._send("STOP")
                stop_requested = True
            if process.is_alive():
                self._send("SHUTDOWN")
                self._closed.wait(3.0)
        except SupervisorClientError:
            pass
        self._stop_threads.set()
        process.join(timeout=3.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        self._process = None
        self._connected = False
        return bool(stop_requested and self.last_status.get("stop_confirmed"))
