import unittest

from vision_app.motor_backend import MotorBackend, MotorFeedback
from vision_app.python_motor_controller import (
    MotorControlError,
    MotorControlState,
    PythonMotorController,
)


class FakeBackend(MotorBackend):
    name = "fake"
    is_real = False

    def __init__(self):
        self._connected = False
        self.commands = []
        self.feedback = []

    @property
    def connected(self):
        return self._connected

    def connect(self):
        self._connected = True

    def activate(self):
        self.commands.append("activate")

    def start(self):
        self.commands.append("start")

    def set_target_rpm(self, rpm):
        self.commands.append(rpm)

    def read_feedback(self, timeout=0.0):
        del timeout
        return self.feedback.pop(0) if self.feedback else None

    def stop(self, repeat=5, interval_s=0.01):
        del repeat, interval_s
        self.commands.append(0)

    def close(self):
        self._connected = False


class PythonMotorControllerTests(unittest.TestCase):
    def test_direct_mode_requires_fresh_feedback_then_sends_target(self):
        backend = FakeBackend()
        controller = PythonMotorController(backend)
        controller.connect()
        self.assertEqual(backend.commands, ["activate"])
        with self.assertRaises(MotorControlError):
            controller.arm(now=1.0)
        self.assertEqual(backend.commands, ["activate"])
        backend.feedback.append(MotorFeedback(12.0, 1.0))
        controller.poll_feedback()
        controller.arm(now=1.1)
        self.assertEqual(backend.commands[-1], "start")
        controller.set_target_rpm(100)
        controller.tick(now=1.11)
        self.assertEqual(controller.state, MotorControlState.RUNNING)
        self.assertEqual(backend.commands[-1], 100)

    def test_stale_feedback_latches_fault_and_zero(self):
        backend = FakeBackend()
        controller = PythonMotorController(backend, feedback_timeout_s=0.2)
        controller.connect()
        backend.feedback.append(MotorFeedback(0.0, 3.0))
        controller.poll_feedback()
        controller.arm(now=3.0)
        controller.set_target_rpm(50)
        controller.tick(now=3.3)
        self.assertEqual(controller.state, MotorControlState.FAULT)
        self.assertEqual(backend.commands[-1], 0)


if __name__ == "__main__":
    unittest.main()
