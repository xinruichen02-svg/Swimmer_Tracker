import socket
import time
import unittest

from vision_app.motor_backend import MotorBackendError
from vision_app.python_motor_controller import PythonMotorController
from vision_app.tcp_motor_backend import TcpMotorBackend


class TcpBackendTests(unittest.TestCase):
    def setUp(self):
        self.client, self.server = socket.socketpair()
        self.backend = TcpMotorBackend("test", 8888, socket_factory=lambda *_args, **_kwargs: self.client)

    def tearDown(self):
        self.backend.close()
        self.server.close()

    def receive_until(self, expected):
        self.server.settimeout(1)
        data = b""
        while expected not in data:
            data += self.server.recv(4096)
        return data

    def test_command_order_and_stream_drain(self):
        self.backend.connect(); self.backend.activate(); self.backend.start(); self.backend.set_target_rpm(-25)
        data = self.receive_until(b"T-25\n")
        self.assertIn(b"P\nT0\nT0\nS\nT-25\n", data)
        self.server.sendall(b"ack one\nack ")
        self.server.sendall(b"two\n")
        deadline = time.monotonic() + 1
        while self.backend.raw_lines.qsize() < 2 and time.monotonic() < deadline: time.sleep(0.01)
        self.assertEqual(self.backend.raw_lines.get_nowait(), "ack one")
        self.assertEqual(self.backend.raw_lines.get_nowait(), "ack two")

    def test_no_feedback_controller_can_arm(self):
        controller = PythonMotorController(self.backend)
        controller.connect(); controller.arm(); controller.set_target_rpm(10); controller.tick()
        self.assertIn(b"T10\n", self.receive_until(b"T10\n"))

    def test_remote_close_surfaces_error(self):
        self.backend.connect(); self.server.close()
        deadline = time.monotonic() + 1
        while self.backend.connected and time.monotonic() < deadline: time.sleep(0.01)
        with self.assertRaises(MotorBackendError): self.backend.read_feedback()
        # Keep tearDown idempotent on Windows builds without AF_UNIX.
        self.server = socket.socket()
