from __future__ import annotations


PROTOCOL_RPM_LIMIT = 2047


class MotorProtocolError(ValueError):
    """Raised when a TCP motor command is invalid."""


def encode_start() -> bytes:
    return b"S\n"


def encode_stop() -> bytes:
    return b"P\n"


def encode_target_rpm(rpm: int) -> bytes:
    if isinstance(rpm, bool) or not isinstance(rpm, int):
        raise MotorProtocolError("目标 RPM 必须是整数")
    if not -PROTOCOL_RPM_LIMIT <= rpm <= PROTOCOL_RPM_LIMIT:
        raise MotorProtocolError("目标 RPM 超出协议范围 -2047..2047")
    return f"T{rpm}\n".encode("ascii")
