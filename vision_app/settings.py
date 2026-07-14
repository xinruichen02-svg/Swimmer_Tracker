from __future__ import annotations

import math
from dataclasses import dataclass


class SettingsError(ValueError):
    """Raised when a control setting is unsafe or internally inconsistent."""


def _finite_number(name: str, value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SettingsError(f"{name} 必须是数字")
    number = float(value)
    if not math.isfinite(number):
        raise SettingsError(f"{name} 必须是有限数字")
    if positive and number <= 0.0:
        raise SettingsError(f"{name} 必须大于 0")
    return number


@dataclass(frozen=True)
class ControlSettings:
    backend: str = "virtual"
    serial_port: str = ""
    can_interface: str = ""
    can_channel: str = ""
    can_bitrate: int = 1_000_000
    control_mode: str = "driver_pid"
    pixels_per_meter: float = 120.0
    rpm_per_mps: float = 1.0
    camera_axis_sign: int = 1
    motor_axis_sign: int = 1
    rpm_limit: int = 2047
    max_rpm_rate_per_s: float = 500.0
    displacement_window_size: int = 7
    displacement_window_s: float = 0.30
    vision_timeout_s: float = 0.25
    telemetry_timeout_s: float = 0.35
    command_interval_s: float = 0.05
    max_offset_fraction: float = 0.45

    def validated(self) -> "ControlSettings":
        if self.backend not in ("virtual", "arduino_serial", "python_can"):
            raise SettingsError("backend 必须是 virtual、arduino_serial 或 python_can")
        if self.control_mode not in ("driver_pid", "ino_pid_compat"):
            raise SettingsError("control_mode 必须是 driver_pid 或 ino_pid_compat")
        if isinstance(self.can_bitrate, bool) or not isinstance(self.can_bitrate, int) or self.can_bitrate <= 0:
            raise SettingsError("can_bitrate 必须是正整数")
        _finite_number("pixels_per_meter", self.pixels_per_meter, positive=True)
        _finite_number("rpm_per_mps", self.rpm_per_mps, positive=True)
        _finite_number("max_rpm_rate_per_s", self.max_rpm_rate_per_s, positive=True)
        _finite_number("displacement_window_s", self.displacement_window_s, positive=True)
        _finite_number("vision_timeout_s", self.vision_timeout_s, positive=True)
        _finite_number("telemetry_timeout_s", self.telemetry_timeout_s, positive=True)
        _finite_number("command_interval_s", self.command_interval_s, positive=True)
        offset_fraction = _finite_number("max_offset_fraction", self.max_offset_fraction, positive=True)
        if offset_fraction >= 0.5:
            raise SettingsError("max_offset_fraction 必须小于 0.5")
        if self.camera_axis_sign not in (-1, 1) or isinstance(self.camera_axis_sign, bool):
            raise SettingsError("camera_axis_sign 只能是 -1 或 +1")
        if self.motor_axis_sign not in (-1, 1) or isinstance(self.motor_axis_sign, bool):
            raise SettingsError("motor_axis_sign 只能是 -1 或 +1")
        if isinstance(self.rpm_limit, bool) or not isinstance(self.rpm_limit, int):
            raise SettingsError("rpm_limit 必须是整数")
        if not 1 <= self.rpm_limit <= 2047:
            raise SettingsError("rpm_limit 必须位于 1..2047")
        if isinstance(self.displacement_window_size, bool) or not isinstance(self.displacement_window_size, int):
            raise SettingsError("displacement_window_size 必须是整数")
        if self.displacement_window_size < 3:
            raise SettingsError("displacement_window_size 至少为 3")
        if self.command_interval_s >= 0.5:
            raise SettingsError("命令周期必须小于 Arduino 500 ms 看门狗超时")
        return self


@dataclass
class CalibrationConfirmation:
    confirmed: bool = False
    _signature: tuple[float, float, int, int] | None = None

    @staticmethod
    def signature(settings: ControlSettings) -> tuple[float, float, int, int]:
        settings.validated()
        return (
            float(settings.pixels_per_meter),
            float(settings.rpm_per_mps),
            settings.camera_axis_sign,
            settings.motor_axis_sign,
        )

    def confirm(self, settings: ControlSettings) -> None:
        self._signature = self.signature(settings)
        self.confirmed = True

    def is_confirmed_for(self, settings: ControlSettings) -> bool:
        return self.confirmed and self._signature == self.signature(settings)

    def invalidate(self) -> None:
        self.confirmed = False
        self._signature = None
