import unittest

from vision_app.motor_protocol import (
    MotorProtocolError,
    encode_start,
    encode_stop,
    encode_target_rpm,
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



if __name__ == "__main__":
    unittest.main()
