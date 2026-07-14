from __future__ import annotations

from dataclasses import dataclass


CAN_BITRATE = 1_000_000
MOTOR_ID = 2
SPEED_COMMAND_ID = 0x202
ACTIVATE_COMMAND_ID = 0x300
SPEED_FEEDBACK_ID = 0x208
CAN_DLC = 8
RPM_LIMIT = 2047


class CanProtocolError(ValueError):
    """Raised when a CAN frame cannot safely represent the INO protocol."""


@dataclass(frozen=True)
class CanFrame:
    arbitration_id: int
    data: bytes
    is_extended_id: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.arbitration_id, bool) or not isinstance(self.arbitration_id, int):
            raise CanProtocolError("CAN ID 必须是整数")
        if not 0 <= self.arbitration_id <= 0x7FF:
            raise CanProtocolError("仅支持 11 位标准 CAN ID")
        if not isinstance(self.data, bytes):
            raise CanProtocolError("CAN 数据必须是 bytes")
        if len(self.data) > CAN_DLC:
            raise CanProtocolError("经典 CAN 数据长度不能超过 8")
        if self.is_extended_id:
            raise CanProtocolError("INO 协议只使用标准帧")


def _motor_offset(motor_id: int) -> int:
    if isinstance(motor_id, bool) or not isinstance(motor_id, int) or not 1 <= motor_id <= 4:
        raise CanProtocolError("电机编号必须位于 1..4")
    return (motor_id - 1) * 2


def _signed_int16(value: int, name: str) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanProtocolError(f"{name} 必须是整数")
    if not -32768 <= value <= 32767:
        raise CanProtocolError(f"{name} 超出 int16 范围")
    return value.to_bytes(2, byteorder="big", signed=True)


def encode_activate(motor_id: int = MOTOR_ID) -> CanFrame:
    _motor_offset(motor_id)
    payload = bytearray([0xFF] * CAN_DLC)
    payload[motor_id - 1] = 0x00
    return CanFrame(ACTIVATE_COMMAND_ID, bytes(payload))


def encode_speed_command(rpm: int, motor_id: int = MOTOR_ID) -> CanFrame:
    if isinstance(rpm, bool) or not isinstance(rpm, int):
        raise CanProtocolError("目标 RPM 必须是整数")
    if not -RPM_LIMIT <= rpm <= RPM_LIMIT:
        raise CanProtocolError(f"目标 RPM 必须位于 -{RPM_LIMIT}..{RPM_LIMIT}")
    offset = _motor_offset(motor_id)
    payload = bytearray([0xFF] * CAN_DLC)
    payload[offset : offset + 2] = _signed_int16(rpm, "目标 RPM")
    return CanFrame(SPEED_COMMAND_ID, bytes(payload))


def decode_speed_command(frame: CanFrame, motor_id: int = MOTOR_ID) -> int:
    if frame.arbitration_id != SPEED_COMMAND_ID or frame.is_extended_id:
        raise CanProtocolError("不是有效的转速命令帧")
    if len(frame.data) != CAN_DLC:
        raise CanProtocolError("转速命令帧 DLC 必须为 8")
    offset = _motor_offset(motor_id)
    return int.from_bytes(frame.data[offset : offset + 2], byteorder="big", signed=True)


def encode_speed_feedback(actual_rpm: int) -> CanFrame:
    payload = bytearray(CAN_DLC)
    payload[4:6] = _signed_int16(actual_rpm, "反馈 RPM")
    return CanFrame(SPEED_FEEDBACK_ID, bytes(payload))


def decode_speed_feedback(frame: CanFrame) -> int:
    if frame.arbitration_id != SPEED_FEEDBACK_ID or frame.is_extended_id:
        raise CanProtocolError("不是有效的转速反馈帧")
    if len(frame.data) < 6:
        raise CanProtocolError("转速反馈帧 DLC 不能小于 6")
    return int.from_bytes(frame.data[4:6], byteorder="big", signed=True)

