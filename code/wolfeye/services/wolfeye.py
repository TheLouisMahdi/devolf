"""Direct Python ports of WolfEye master signal, ADC, TCC and AR behavior.

Reference: majidnow/wolfeye@7e58f4af439c6fa9c9db51e4558936264401732a.
BeachEye remains responsible for transport and settings serialization.
"""
from __future__ import annotations

import math
import struct

from wolfeye.services.ar_rules import cycle_ar_stage

SIGNAL_CHANNELS = 10
SIGNAL_SAMPLES = 64
# Defaults for 64-sample devices; INFO flags & 0x02 selects 32 at runtime.
SIGNAL_PAYLOAD_BYTES = SIGNAL_CHANNELS * SIGNAL_SAMPLES * 4
SIGNAL_STRUCT_BYTES = (SIGNAL_CHANNELS + 2) * SIGNAL_SAMPLES * 4
SIGNAL_SAMPLE_INTERVAL_S = 0.0003125
SIGNAL_SAMPLE_RATE_HZ = 1.0 / SIGNAL_SAMPLE_INTERVAL_S
SIGNAL_CHANNEL_NAMES = ("Ia", "Ib", "Ic", "In", "Va", "Vb", "Vc", "Vr", "Vs", "Vt")

def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


# Constants follow the IEC_Def/ANSI_Def field order in protection_types.h.
# Round each float expression as in WolfEye master TCCCalculator.cpp.
_IEC = {9: (80, 2), 10: (13.5, 1), 11: (0.14, 0.02), 12: (120, 1)}
_ANSI = {1: (6.407, 0.025, 2), 2: (2.855, 0.0712, 2),
         3: (0.0086, 0.0185, 0.02), 4: (0.00172, 0.0037, 0.02),
         5: (1.281, 0.005, 2), 6: (64.07, 0.25, 2),
         7: (28.55, 0.0712, 2), 8: (0.086, 0.185, 0.02)}


def calculate_tcc_trip_ms(
    curve_type: int, pickup: int, multiplier: float, minimum: int,
    maximum: int, adder: int, definite_time: int, current: int,
) -> int | None:
    if curve_type not in range(13) or not 0 < pickup <= 65535 or not 0 <= current <= 65535:
        return None
    if any(not 0 <= value <= 0xFFFFFFFF for value in (minimum, maximum, adder, definite_time)):
        return None
    if not math.isfinite(multiplier) or multiplier < 0:
        return None
    if curve_type == 0:
        return definite_time
    if current <= pickup:
        return maximum
    try:
        tm = _float32(multiplier)
        ratio = _float32(current / pickup)
        if curve_type in _IEC:
            a, exponent = map(_float32, _IEC[curve_type])
            denominator = _float32(_float32(math.pow(ratio, exponent)) - 1)
            trip = _float32(_float32(1000 * _float32(a * tm)) / denominator)
        else:
            a, b, exponent = map(_float32, _ANSI[curve_type])
            denominator = _float32(_float32(math.pow(ratio, exponent)) - 1)
            trip = _float32(_float32(_float32(_float32(a / denominator) + b) * tm) * 1000)
        if not math.isfinite(trip):
            return None
        # Company converts to uint32 milliseconds before adding Ta and clamping.
        trip_ms = (int(trip) + adder) & 0xFFFFFFFF
        return min(maximum, max(minimum, trip_ms))
    except (OverflowError, ZeroDivisionError, ValueError):
        return None


def decode_signal(payload: bytes, samples: int = SIGNAL_SAMPLES) -> list[list[float]]:
    if samples not in (32, 64):
        raise ValueError("BeachEye signal sample count must be 32 or 64")
    # INFO selects the float32 channel stride, as in company load_signal().
    # Company load_signal() reads only 10 * samples floats from the start.
    # 32-sample firmware can still send a fixed 64-sample-sized buffer; its
    # trailing bytes are not additional plot channels or a different profile.
    payload_bytes = SIGNAL_CHANNELS * samples * 4
    struct_bytes = (SIGNAL_CHANNELS + 2) * samples * 4
    accepted_bytes = {payload_bytes, struct_bytes}
    if samples == 32:
        accepted_bytes.update((SIGNAL_PAYLOAD_BYTES, SIGNAL_STRUCT_BYTES))
    if len(payload) not in accepted_bytes:
        raise ValueError(
            f"Unexpected BeachEye signal payload size: {len(payload)} bytes "
            f"(expected {', '.join(map(str, sorted(accepted_bytes)))} for {samples} samples)"
        )
    values = struct.unpack_from(f"<{SIGNAL_CHANNELS * samples}f", payload)
    channels = [list(values[i * samples:(i + 1) * samples]) for i in range(SIGNAL_CHANNELS)]
    if any(not math.isfinite(value) for channel in channels for value in channel):
        raise ValueError("BeachEye signal response contains a non-finite float32 sample")
    return channels


def decode_adc(payload: bytes, samples: int = SIGNAL_SAMPLES) -> list[list[float]]:
    if samples not in (32, 64):
        raise ValueError("BeachEye ADC sample count must be 32 or 64")
    cycle_bytes = SIGNAL_CHANNELS * samples * 2
    if not payload or len(payload) % cycle_bytes:
        raise ValueError(f"Incomplete BeachEye ADC payload: {len(payload)} bytes (expected multiples of {cycle_bytes})")
    channels: list[list[float]] = [[] for _ in range(SIGNAL_CHANNELS)]
    words = struct.unpack(f"<{len(payload) // 2}H", payload)
    half = samples // 2
    for cycle in range(len(payload) // cycle_bytes):
        base = cycle * SIGNAL_CHANNELS * samples
        for phase in range(2):
            voltages = base + phase * SIGNAL_CHANNELS * half
            currents = voltages + 6 * half
            for channel in range(6):
                channels[channel + 4].extend(float(words[voltages + i * 6 + channel]) for i in range(half))
            for channel in range(4):
                channels[channel].extend(float(words[currents + i * 4 + channel]) for i in range(half))
    return channels
