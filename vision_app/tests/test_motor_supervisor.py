import multiprocessing
import time
import unittest

from vision_app.motor_supervisor import BackendConfig, supervisor_process
from vision_app.supervisor_client import MotorSupervisorClient


class MotorSupervisorTests(unittest.TestCase):
    def test_virtual_supervisor_runs_and_confirms_stop(self):
        client = MotorSupervisorClient()
        try:
            client.connect(BackendConfig())
            self.assertTrue(client.connected)
            self.assertFalse(client.is_real)
            client.send_target_rpm(150)
            client.send_start()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                client.send_target_rpm(150)
                if client.last_status.get("state") == "RUNNING" and abs(client.last_status.get("actual_rpm") or 0) > 50:
                    break
                time.sleep(0.05)
            self.assertEqual(client.last_status.get("state"), "RUNNING", client.last_status)
            client.send_stop()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not client.last_status.get("stop_confirmed"):
                time.sleep(0.05)
            self.assertTrue(client.last_status.get("stop_confirmed"))
        finally:
            client.disconnect(send_stop=True)

    def test_invalid_real_can_does_not_silently_become_virtual(self):
        client = MotorSupervisorClient()
        with self.assertRaises(Exception):
            client.connect(BackendConfig(backend="python_can", can_interface="virtual", can_channel="x"))
        self.assertFalse(client.connected)

    def test_missing_heartbeat_latches_fault_and_zero(self):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=supervisor_process,
            args=(child, BackendConfig(), 0.2, 0.5),
        )
        process.start()
        child.close()
        try:
            self.assertTrue(parent.poll(3.0))
            ready = parent.recv()
            self.assertEqual(ready.get("kind"), "READY")
            now = time.monotonic()
            parent.send({"kind": "TARGET", "sequence": 1, "sent_at": now, "rpm": 100})
            parent.send({"kind": "ARM", "sequence": 2, "sent_at": now})
            deadline = time.monotonic() + 2.0
            fault_status = None
            while time.monotonic() < deadline:
                if parent.poll(0.1):
                    message = parent.recv()
                    status = message.get("status") or {}
                    if status.get("state") == "FAULT":
                        fault_status = status
                        break
            self.assertIsNotNone(fault_status)
            self.assertIn("心跳", fault_status.get("fault", ""))
            self.assertEqual(fault_status.get("output_rpm"), 0)
            parent.send({"kind": "SHUTDOWN"})
        finally:
            process.join(timeout=3.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            parent.close()

    def test_stale_target_faults_even_when_heartbeat_continues(self):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=supervisor_process,
            args=(child, BackendConfig(), 0.5, 0.2),
        )
        process.start()
        child.close()
        try:
            self.assertTrue(parent.poll(3.0))
            self.assertEqual(parent.recv().get("kind"), "READY")
            sequence = 1
            now = time.monotonic()
            parent.send({"kind": "TARGET", "sequence": sequence, "sent_at": now, "rpm": 100})
            parent.send({"kind": "ARM", "sequence": sequence + 1, "sent_at": now})
            deadline = time.monotonic() + 2.0
            fault_status = None
            while time.monotonic() < deadline:
                sequence += 1
                parent.send({"kind": "HEARTBEAT", "sequence": sequence, "sent_at": time.monotonic()})
                stop_wait = time.monotonic() + 0.05
                while time.monotonic() < stop_wait:
                    if parent.poll(0.01):
                        status = (parent.recv().get("status") or {})
                        if status.get("state") == "FAULT":
                            fault_status = status
                            break
                if fault_status:
                    break
            self.assertIsNotNone(fault_status)
            self.assertIn("目标命令", fault_status.get("fault", ""))
            self.assertEqual(fault_status.get("output_rpm"), 0)
            parent.send({"kind": "SHUTDOWN"})
        finally:
            process.join(timeout=3.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            parent.close()


if __name__ == "__main__":
    unittest.main()
