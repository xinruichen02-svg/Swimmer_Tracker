import time
import unittest

from vision_app.virtual_motor_backend import VirtualMotorBackend


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
