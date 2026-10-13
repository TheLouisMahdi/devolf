from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from wolfeye.point_schema import (
    ANALOG_POINT_NAMES,
    BINARY_INPUT_POINT_NAMES,
    COUNTER_POINT_NAMES,
)

ANALOG_NAMES = list(ANALOG_POINT_NAMES)
BINARY_NAMES = list(BINARY_INPUT_POINT_NAMES)
COUNTER_NAMES = list(COUNTER_POINT_NAMES)


@dataclass
class DeviceInfo:
    ip: str = "192.168.137.10"
    model: str = "—"
    firmware: int = 0
    hardware: int = 0
    bootloader: int = 0
    build: int = 0
    flags: int = 0
    commit: str = ""
    connected: bool = False
    transport: str = "Offline"


@dataclass
class MeasurementSnapshot:
    analog: dict[str, float] = field(default_factory=dict)
    binary: dict[str, bool] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class EventRecord:
    timestamp: datetime
    kind: str
    point: str
    value: str
    value_bits: int = 0
