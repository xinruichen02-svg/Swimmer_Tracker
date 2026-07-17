import unittest
from pathlib import Path


INO_PATH = (
    Path(Path(__file__).resolve().anchor)
    / "水下滑轨机器人"
    / "src"
    / "pidnew2.ino"
)


class InoWatchdogSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = INO_PATH.read_text(encoding="utf-8")

    def test_verified_can_protocol_constants_are_preserved(self):
        self.assertIn("#define CAN_BAUD_RATE   CAN_1000KBPS", self.source)
        self.assertIn("#define MOTOR_ID        1", self.source)
        self.assertIn("#define SPEED_CMD_ID    0x202", self.source)
        self.assertIn("#define ACTIVATE_CMD_ID 0x300", self.source)
        self.assertIn("#define SPEED_FEEDBACK_ID 0x208", self.source)
        self.assertIn("MCP_16MHZ", self.source)
        self.assertIn("const long sendInterval = 10;", self.source)

    def test_mega_hardware_spi_and_optional_interrupt_are_documented(self):
        self.assertIn("#define MCP2515_CS_PIN  10", self.source)
        self.assertIn("#define MCP2515_INT_PIN 2", self.source)
        self.assertIn("SO/MISO->D50", self.source)
        self.assertIn("SI/MOSI->D51", self.source)
        self.assertIn("SCK->D52", self.source)

    def test_watchdog_is_500_ms_and_uses_wrap_safe_subtraction(self):
        self.assertIn("const unsigned long CONTROL_TIMEOUT_MS = 500;", self.source)
        self.assertIn(
            "(unsigned long)(now - lastControlCommandTime) > CONTROL_TIMEOUT_MS",
            self.source,
        )
        self.assertIn("safeStopMotor();", self.source)
        self.assertIn("WATCHDOG_TIMEOUT", self.source)

    def test_only_valid_start_and_integer_target_refresh_watchdog(self):
        self.assertIn("lastControlCommandTime = millis();", self.source)
        self.assertIn("if (!validNumber)", self.source)
        self.assertIn("目标转速必须是整数", self.source)
        self.assertIn("speed >= -2047 && speed <= 2047", self.source)

    def test_safe_stop_clears_enable_target_and_pid_output(self):
        start = self.source.index("void safeStopMotor()")
        stop = self.source.index("void serialEvent()", start)
        body = self.source[start:stop]
        self.assertIn("motorEnable = false;", body)
        self.assertIn("targetRPM = 0;", body)
        self.assertIn("pidOutput = 0;", body)
        self.assertIn("sendSpeedCommand(MOTOR_ID, 0);", body)

    def test_can_feedback_and_send_failure_guards_are_present(self):
        self.assertIn("const unsigned long CAN_FEEDBACK_TIMEOUT_MS = 200;", self.source)
        self.assertIn("const uint8_t MAX_CONSECUTIVE_SEND_FAILURES = 3;", self.source)
        self.assertIn("CAN_FEEDBACK_TIMEOUT", self.source)
        self.assertIn("CAN_TX_FAILURE", self.source)
        self.assertIn("feedbackIsFresh(now)", self.source)


if __name__ == "__main__":
    unittest.main()
