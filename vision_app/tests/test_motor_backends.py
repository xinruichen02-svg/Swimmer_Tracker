import time
import unittest

from vision_app.arduino_serial_backend import ArduinoSerialBackend
from vision_app.motor_backend import MotorBackendError
from vision_app.motor_link import MotorLink
from vision_app.virtual_motor_backend import VirtualMotorBackend


class FakeSerial:
    def __init__(self, **_kwargs):
        self.is_open = True
        self.writes = []

    def write(self, payload):
        self.writes.append(payload)
        return len(payload)

    def flush(self):
        return None

    def read(self, _size):
        time.sleep(0.001)
        return b""

    def close(self):
        self.is_open = False


class ArduinoBackendTests(unittest.TestCase):
    def test_adapter_preserves_ino_command_order(self):
        serials = []
        link = MotorLink(serial_factory=lambda **kwargs: serials.append(FakeSerial(**kwargs)) or serials[-1])
        backend = ArduinoSerialBackend("COM_TEST", link=link)
        backend.connect()
        backend.activate()
        backend.set_target_rpm(25)
        backend.stop()
        self.assertEqual(serials[0].writes, [b"P\n", b"T0\n", b"S\n", b"T25\n", b"P\n"])
        backend.close()

    def test_adapter_rejects_missing_port(self):
        with self.assertRaises(MotorBackendError):
            ArduinoSerialBackend("").connect()


class VirtualBackendTests(unittest.TestCase):
    def test_virtual_bus_round_trip(self):
        backend = VirtualMotorBackend()
        try:
            backend.connect()
            backend.activate()
            feedback = backend.read_feedback(timeout=0.5)
            self.assertIsNotNone(feedback)
            backend.set_target_rpm(200)
            deadline = time.monotonic() + 1.0
            actual = 0.0
            while time.monotonic() < deadline and actual < 150:
                event = backend.read_feedback(timeout=0.1)
                if event is not None:
                    actual = event.actual_rpm
            self.assertGreaterEqual(actual, 150)
            backend.stop(interval_s=0.0)
        finally:
            backend.close()


if __name__ == "__main__":
    unittest.main()
