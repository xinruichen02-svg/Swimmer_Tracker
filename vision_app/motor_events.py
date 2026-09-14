from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MotorTelemetry:
    target_rpm: float
    actual_rpm: float
    output_rpm: float
    received_at: float


@dataclass(frozen=True)
class MotorEvent:
    kind: str
    message: str
    received_at: float
    telemetry: MotorTelemetry | None = None
