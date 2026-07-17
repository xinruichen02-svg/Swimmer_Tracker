import time
import unittest
import queue

from vision_app.motor_link import (
    MotorProtocolError,
    TelemetryParser,
    encode_start,
    encode_stop,
    encode_target_rpm,
    encode_pid_tunings,
    MotorLink,
    MotorLinkEvent,
)


class CommandEncodingTests(unittest.TestCase):
    def test_fixed_commands(self):
        self.assertEqual(encode_start(), b"S\n")
        self.assertEqual(encode_stop(), b"P\n")

    def test_target_command_supports_both_directions(self):
        self.assertEqual(encode_target_rpm(300), b"T300\n")
        self.assertEqual(encode_target_rpm(-300), b"T-300\n")
        self.assertEqual(encode_target_rpm(0), b"T0\n")

    def test_target_command_rejects_wrong_type_and_range(self):
        for value in (1.5, True, 2048, -2048, "12"):
            with self.subTest(value=value), self.assertRaises(MotorProtocolError):
                encode_target_rpm(value)

    def test_pid_tunings_match_ino_online_commands(self):
        self.assertEqual(
            encode_pid_tunings(1.0, 0.05, 0.02),
            (b"KP=1\n", b"KI=0.05\n", b"KD=0.02\n"),
        )
        for values in ((-1, 0, 0), (float("nan"), 0, 0), (True, 0, 0)):
            with self.subTest(values=values), self.assertRaises(MotorProtocolError):
                encode_pid_tunings(*values)


class TelemetryParserTests(unittest.TestCase):
    def test_complete_chinese_telemetry(self):
        parser = TelemetryParser()
        events = parser.feed("目标:300.00,实际:-12.00,输出:280.50\n".encode("utf-8"), 5.0)

        self.assertEqual(len(events), 1)
        telemetry = events[0]
        self.assertEqual(telemetry.target_rpm, 300.0)
        self.assertEqual(telemetry.actual_rpm, -12.0)
        self.assertEqual(telemetry.output_rpm, 280.5)
        self.assertEqual(telemetry.received_at, 5.0)

    def test_fragmented_line_is_emitted_only_when_complete(self):
        parser = TelemetryParser()
        self.assertEqual(parser.feed("目标:1,实".encode("utf-8"), 1.0), [])
        events = parser.feed("际:2,输出:3\r\n".encode("utf-8"), 2.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].actual_rpm, 2.0)
        self.assertEqual(events[0].received_at, 2.0)

    def test_unknown_and_invalid_lines_do_not_emit_telemetry(self):
        parser = TelemetryParser()
        payload = (
            "===== 系统启动 =====\n"
            "目标:abc,实际:2,输出:3\n"
            "[错误] 未知指令\n"
        ).encode("utf-8")
        self.assertEqual(parser.feed(payload, 1.0), [])


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


class MotorLinkIntegrationTests(unittest.TestCase):
    def test_connect_stops_first_and_start_order_is_target_then_start(self):
        instances = []

        def factory(**kwargs):
            instance = FakeSerial(**kwargs)
            instances.append(instance)
            return instance

        link = MotorLink(serial_factory=factory)
        link.events.put(MotorLinkEvent("telemetry", "旧事件", 0.0))
        link.connect("COM_TEST")
        fake = instances[0]
        self.assertEqual(fake.writes, [b"P\n"])
        with self.assertRaises(queue.Empty):
            link.events.get_nowait()

        link.send_target_rpm(0)
        link.send_start()
        self.assertEqual(fake.writes[-2:], [b"T0\n", b"S\n"])

        link.send_pid_tunings(1.0, 0.05, 0.02)
        self.assertEqual(fake.writes[-3:], [b"KP=1\n", b"KI=0.05\n", b"KD=0.02\n"])

        self.assertTrue(link.disconnect(send_stop=True))
        self.assertEqual(fake.writes[-1], b"P\n")


if __name__ == "__main__":
    unittest.main()
