import unittest

from vision_app.can_protocol import (
    ACTIVATE_COMMAND_ID,
    SPEED_COMMAND_ID,
    SPEED_FEEDBACK_ID,
    CanFrame,
    CanProtocolError,
    decode_speed_command,
    decode_speed_feedback,
    encode_activate,
    encode_speed_command,
    encode_speed_feedback,
)


class CanProtocolTests(unittest.TestCase):
    def test_activation_frame_matches_ino_motor_two_layout(self):
        frame = encode_activate()
        self.assertEqual(frame.arbitration_id, ACTIVATE_COMMAND_ID)
        self.assertEqual(frame.data, bytes.fromhex("ff00ffffffffffff"))
        self.assertFalse(frame.is_extended_id)

    def test_speed_command_matches_ino_big_endian_slot(self):
        self.assertEqual(encode_speed_command(300).arbitration_id, SPEED_COMMAND_ID)
        self.assertEqual(encode_speed_command(300).data, bytes.fromhex("ffff012cffffffff"))
        self.assertEqual(encode_speed_command(-300).data, bytes.fromhex("fffffed4ffffffff"))
        self.assertEqual(decode_speed_command(encode_speed_command(-2047)), -2047)
        self.assertEqual(decode_speed_command(encode_speed_command(2047)), 2047)

    def test_feedback_uses_bytes_four_and_five_as_signed_int16(self):
        frame = encode_speed_feedback(-1234)
        self.assertEqual(frame.arbitration_id, SPEED_FEEDBACK_ID)
        self.assertEqual(frame.data[4:6], bytes.fromhex("fb2e"))
        self.assertEqual(decode_speed_feedback(frame), -1234)
        six_byte_frame = CanFrame(SPEED_FEEDBACK_ID, bytes.fromhex("00000000007b"))
        self.assertEqual(decode_speed_feedback(six_byte_frame), 123)

    def test_invalid_values_and_frames_are_rejected(self):
        for value in (True, 1.2, 2048, -2048, "1"):
            with self.subTest(value=value), self.assertRaises(CanProtocolError):
                encode_speed_command(value)
        with self.assertRaises(CanProtocolError):
            decode_speed_feedback(CanFrame(0x207, b"\0" * 8))
        with self.assertRaises(CanProtocolError):
            decode_speed_feedback(CanFrame(SPEED_FEEDBACK_ID, b"\0" * 5))
        with self.assertRaises(CanProtocolError):
            CanFrame(0x800, b"")


if __name__ == "__main__":
    unittest.main()
