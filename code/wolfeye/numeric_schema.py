"""Storage limits for the WolfEye master numeric editors.

Company master 989f9ff disables MenuItemAttr validation. Keep only ABI limits,
in UI units, instead of applying the embedded menu's engineering ranges.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


@dataclass(frozen=True)
class NumericSpec:
    minimum: float
    maximum: float
    decimals: int = 0
    scale: int = 1
    storage: str = "uint16"

    def validate(self, value: Any, path: str) -> None:
        number = float(value)
        if not math.isfinite(number) or not self.minimum <= number <= self.maximum:
            raise ValueError(f"{path}: value must be between {self.minimum:g} and {self.maximum:g}")
        if self.decimals == 0 and number != int(number):
            raise ValueError(f"{path}: an integer value is required")


def unsigned(bits: int, scale: int = 1, decimals: int = 0) -> NumericSpec:
    maximum = (2**bits - 1) / scale
    if decimals == 0:
        maximum = math.floor(maximum)
    return NumericSpec(0, maximum, decimals, scale, f"uint{bits}")


U8 = unsigned(8)
U16 = unsigned(16)
U32 = unsigned(32)
TIME = unsigned(32, 1000, 3)
MINUTES = unsigned(32, 60000)
FLOAT = NumericSpec(-3.4028234663852886e38, 3.4028234663852886e38, 6, 1, "float32")
SIGNED_CONDUCTANCE = NumericSpec(-327.68, 327.67, 2, 100, "int16")


def numeric_spec(path: str) -> NumericSpec | None:
    """Resolve a normalized configuration path; unknown fields keep their editor."""
    p = re.sub(r"\.\d+(?=\.|$)", ".*", path)
    if p.startswith("general."):
        if p == "general.io.digital_inputs.validation_time_s":
            return unsigned(8, 1000, 3)
        if p == "general.scada.dnp3.unsolicited.hold_time_s":
            return U8  # Packed as a byte in seconds, not milliseconds.
        if p.endswith("_s") and not p.endswith("max_roc_slip_hz_s"):
            return TIME
        if p.startswith("general.heater."):
            return U8
        if p == "general.system.functions.*.analog_compared_to":
            return U32
        if p == "general.security.password":
            return U32
        if p.startswith("general.system.fault_locator."):
            return unsigned(16, 100 if p.endswith("line_length_km") else 1000,
                            2 if p.endswith("line_length_km") else 3)
        if p == "general.system.lsd_level" or p.endswith("deadbands.voltages_v"):
            return unsigned(16, 1000, 3)
        if p.endswith(("deadbands.battery_voltage_v", "deadbands.frequency_hz")):
            return unsigned(16, 10, 1)
        if p.startswith("general.system.synchronization."):
            name = p.rsplit(".", 1)[-1]
            if name in {"phase_angle_difference_deg", "fundamental_frequency_hz"}:
                return U8
            if name in {"live_bus_voltage_multiplier", "live_line_voltage_multiplier",
                        "bus_max_voltage_multiplier", "line_max_voltage_multiplier"}:
                return unsigned(4, 10, 1)  # Packed into nibbles on the wire.
            if name == "max_slip_frequency_hz":
                return unsigned(4, 100, 2)
            if name in {"voltage_difference_multiplier", "max_slip_frequency_hz",
                        "max_frequency_deviation_hz", "auto_max_slip_hz", "max_roc_slip_hz_s"}:
                return unsigned(8, 100, 2)
        if p.startswith(("general.measurement.", "general.scada.", "general.security.")):
            return U16
        return None
    if not p.startswith("protection.groups.*."):
        return None
    p = p.removeprefix("protection.groups.*.")
    if p.startswith("master.tcc_view."):
        name = p.rsplit(".", 1)[-1]
        return {
            "test_point_a": U16,
            "min_current_a": NumericSpec(1, 65534),
            "max_current_a": NumericSpec(2, 65535),
            "min_time_s": NumericSpec(0.001, TIME.maximum - 0.001, 3),
            "max_time_s": NumericSpec(0.002, TIME.maximum, 3),
        }.get(name)
    if p.endswith(("clp.time_min", "clp.recognition_min", "timer.time_min")):
        return MINUTES
    if p.endswith("moving_average_window") or p.endswith("_s"):
        return TIME
    if ".elements." in p:
        name = p.rsplit(".", 1)[-1]
        if name in {"time_multiplier", "min_current_multiplier"}:
            return FLOAT
        if name == "max_current_multiplier":
            return unsigned(16, 100, 2)
        if name == "pickup_a":
            return U16
    if p in {"clp.multiplier", "inrush.multiplier"}:
        return FLOAT
    if p.endswith(("forward_susceptance", "reverse_susceptance", "forward_conductance", "reverse_conductance")):
        return SIGNED_CONDUCTANCE
    if p.endswith("min_un_multiplier"):
        return unsigned(8, 100, 2)
    if p.startswith("voltage.") and p.endswith("multiplier"):
        stage = p.split(".")[1]
        return unsigned(32 if stage in {"uv1", "uv2", "uv3"} else 8, 100, 2)
    if p.startswith("master.over_voltage.") and p.endswith("multiplier"):
        return unsigned(32 if p.split(".")[2] == "ov1" else 8, 100, 2)
    if p.endswith("voltage_multiplier"):
        return unsigned(8, 100, 2)
    if p.endswith("pickup_hz"):
        return unsigned(16, 100, 2)
    if ".harmonic." in p and p.endswith("level_pct"):
        return unsigned(16, 10, 1)
    if p.endswith(("timer.operations", "ar_voltage.trip_count")):
        return unsigned(4)
    if p == "sectionalizing.max_trip_count":
        return NumericSpec(1, 3, storage="uint2")
    if p.endswith(("harmonic_level_pct", "pickup_pct", "reduced_percent")):
        return U8
    if p.endswith(("pickup_a", "minimum_in_a", "negative_sequence_min_a", "zero_sequence_min_a", "torque_angle_deg")):
        return U16
    return None


def validate_numeric_config(config: dict[str, Any]) -> None:
    """Reject overflow before mutating the native settings object."""
    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}.{index}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            spec = numeric_spec(path)
            if spec is not None:
                spec.validate(value, path)
    visit(config, "")
