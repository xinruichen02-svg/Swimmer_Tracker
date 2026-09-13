import queue
import unittest

from vision_app.motor_gateway import MotorCommandGateway


class FakeClient:
    def __init__(self):
        self.connected = True
        self.is_real = False
        self.events = queue.Queue()
        self.last_status = {}
        self.targets = []

    def send_target_rpm(self, rpm): self.targets.append(rpm)
    def send_start(self): pass
    def send_stop(self): pass
    def reset_fault(self): pass
    def disconnect(self, send_stop=True): return True


class MotorGatewayTests(unittest.TestCase):
    def test_speed_conversion_limit_and_estimate(self):
        fake = FakeClient(); gateway = MotorCommandGateway(fake)
        gateway.configure_rate_limit(1000)
        gateway.set_expected_speed(1.0, 100.0, -1, 2047, 1.0)
        raw, command = gateway.set_expected_speed(1.0, 100.0, -1, 2047, 2.0)
        self.assertEqual(raw, -100)
        self.assertEqual(command, -100)
        self.assertEqual(fake.targets[-1], -100)
        self.assertEqual(gateway.estimated_speed_mps(100.0, -1), 1.0)

    def test_all_targets_share_slew_and_protocol_limit(self):
        fake = FakeClient(); gateway = MotorCommandGateway(fake)
        gateway.configure_rate_limit(10)
        gateway.set_expected_rpm(5000, 200, 1.0)
        command = gateway.set_expected_rpm(5000, 200, 2.0)
        self.assertEqual(command, 10)
        self.assertEqual(fake.targets, [0, 10])
