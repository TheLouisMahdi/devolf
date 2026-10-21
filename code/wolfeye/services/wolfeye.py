"""ctypes boundary for company WolfEye algorithms; UI/analysis stay in Qt."""
from __future__ import annotations
import ctypes as ct
import math
import os
import sys
from functools import lru_cache
from pathlib import Path

SIGNAL_CHANNELS = 10
SIGNAL_SAMPLES = 64
# Defaults for 64-sample devices; INFO flags & 0x02 selects 32 at runtime.
SIGNAL_PAYLOAD_BYTES = SIGNAL_CHANNELS * SIGNAL_SAMPLES * 4
SIGNAL_STRUCT_BYTES = (SIGNAL_CHANNELS + 2) * SIGNAL_SAMPLES * 4
SIGNAL_SAMPLE_INTERVAL_S = 0.0003125
SIGNAL_SAMPLE_RATE_HZ = 1.0 / SIGNAL_SAMPLE_INTERVAL_S
SIGNAL_CHANNEL_NAMES = ("Ia", "Ib", "Ic", "In", "Va", "Vb", "Vc", "Vr", "Vs", "Vt")

@lru_cache(maxsize=1)
def _native() -> ct.CDLL:
    override = os.environ.get("WOLFEYE_CORE_DIR") or os.environ.get("WOLFEYE_NATIVE_DIR")
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    directory = Path(override) if override else root / "native" / "beacheye"
    path = directory / "wolfeye_core.dll"
    try:
        library = ct.CDLL(str(path))
        library.we_abi_version.argtypes = []
        library.we_abi_version.restype = ct.c_uint32
        if library.we_abi_version() != 1:
            raise ValueError("Unsupported WolfEye core ABI; rebuild both native DLLs")
        library.we_tcc_trip_ms.argtypes = [
            ct.c_uint32, ct.c_uint16, ct.c_float, ct.c_uint32,
            ct.c_uint32, ct.c_uint32, ct.c_uint32, ct.c_uint16,
            ct.POINTER(ct.c_uint32),
        ]
        library.we_tcc_trip_ms.restype = ct.c_int
        library.we_ar_cycle.argtypes = [ct.POINTER(ct.c_uint8), ct.POINTER(ct.c_uint8), ct.c_uint32, ct.c_uint32, ct.c_uint32]
        library.we_ar_cycle.restype = ct.c_int
        for name in ("signal", "adc"):
            function = getattr(library, f"we_{name}")
            function.argtypes = [ct.c_void_p, ct.c_size_t, ct.POINTER(ct.c_float), ct.c_size_t, ct.c_uint32]
            function.restype = ct.c_int
    except (OSError, AttributeError) as exc:
        raise ValueError(f"Cannot load WolfEye C++ core: {path}. Rebuild the native libraries. {exc}") from exc
    return library


def _decode(name: str, payload: bytes, output: object, *args: int) -> int:
    buffer = ct.create_string_buffer(payload)
    count = getattr(_native(), f"we_{name}")(buffer, len(payload), output, *args)
    if count < 0:
        raise ValueError(f"Invalid or incomplete WolfEye {name} payload ({len(payload)} bytes)")
    return count


def cycle_ar_stage(modes: list[int], disabled: list[bool], row: int, stage: int, sef: bool) -> tuple[list[int], list[bool]]:
    count = 4 if sef else 12
    if len(modes) != count or len(disabled) != count:
        raise ValueError("Invalid AR stage pack")
    values = (ct.c_uint8 * count)(*modes)
    blocked = (ct.c_uint8 * count)(*disabled)
    if _native().we_ar_cycle(values, blocked, row, stage, sef) < 0:
        raise ValueError("Invalid AR stage transition")
    return list(values), [bool(value) for value in blocked]


def calculate_tcc_trip_ms(
    curve_type: int, pickup: int, multiplier: float, minimum: int,
    maximum: int, adder: int, definite_time: int, current: int,
) -> int | None:
    if any(not 0 <= value <= 0xFFFFFFFF for value in (minimum, maximum, adder, definite_time)):
        return None
    result = ct.c_uint32()
    status = _native().we_tcc_trip_ms(
        curve_type, pickup, multiplier, minimum, maximum, adder,
        definite_time, current, ct.byref(result),
    )
    return result.value if status == 0 else None


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
    values = (ct.c_float * (SIGNAL_CHANNELS * samples))()
    count = _decode("signal", payload, values, len(values), samples)
    if count != len(values):
        raise ValueError(f"BeachEye signal decoder returned {count} of {len(values)} samples")
    channels = [
        list(values[i * samples : (i + 1) * samples])
        for i in range(SIGNAL_CHANNELS)
    ]
    if any(not math.isfinite(value) for channel in channels for value in channel):
        raise ValueError("BeachEye signal response contains a non-finite float32 sample")
    return channels


def decode_adc(payload: bytes, samples: int = SIGNAL_SAMPLES) -> list[list[float]]:
    if samples not in (32, 64):
        raise ValueError("BeachEye ADC sample count must be 32 or 64")
    cycle_bytes = SIGNAL_CHANNELS * samples * 2
    if not payload or len(payload) % cycle_bytes:
        raise ValueError(f"Incomplete BeachEye ADC payload: {len(payload)} bytes (expected multiples of {cycle_bytes})")
    values = (ct.c_float * (len(payload) // 2))()
    count = _decode("adc", payload, values, len(values), samples)
    if count != len(values):
        raise ValueError(f"BeachEye ADC decoder returned {count} of {len(values)} samples")
    samples = count // SIGNAL_CHANNELS
    return [list(values[i * samples:(i + 1) * samples]) for i in range(SIGNAL_CHANNELS)]
