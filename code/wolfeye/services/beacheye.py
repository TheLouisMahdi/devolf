from __future__ import annotations

import ctypes as ct
import json
import os
import re
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, TypeVar

from wolfeye.models import EventRecord, MeasurementSnapshot

M_TYPE_BI = 0x01
M_TYPE_AI = 0x02
M_TYPE_BC = 0x04
from wolfeye.services.wolfeye import (
    SIGNAL_CHANNELS, SIGNAL_SAMPLES, SIGNAL_PAYLOAD_BYTES, SIGNAL_STRUCT_BYTES,
    SIGNAL_SAMPLE_INTERVAL_S, SIGNAL_SAMPLE_RATE_HZ, SIGNAL_CHANNEL_NAMES,
    cycle_ar_stage, calculate_tcc_trip_ms, decode_signal, decode_adc,
)
EVENT_TIMEZONE_OFFSET_MS = 12_600_000
PROVIDER_CONNECTED = 1
PROVIDER_DISCONNECTED = 2
PROVIDER_RESPONSE = 3
PROVIDER_TIMEOUT = 4
PROVIDER_ERROR = 5
PROVIDER_UPDATE_PROGRESS = 6
PROVIDER_UPDATE_FINISHED = 7
PROVIDER_FIRMWARE = 1
PROVIDER_BOOTLOADER = 2

_ProviderCallback = ct.CFUNCTYPE(
    None,
    ct.c_void_p,
    ct.c_uint32,
    ct.c_uint32,
    ct.c_uint32,
    ct.c_void_p,
    ct.c_size_t,
)


class _Info(ct.Structure):
    _fields_ = [
        (name, ct.c_uint32)
        for name in ("model", "firmware", "hardware", "bootloader", "build", "flags")
    ] + [("commit", ct.c_ubyte * 8)]


class _Point(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in ("type", "index", "value")]


class _NamedPoint(ct.Structure):
    _fields_ = [
        (name, ct.c_uint32)
        for name in ("type", "source_index", "dnp_index", "value")
    ] + [("name", ct.c_char * 64)]


class _Event(ct.Structure):
    _fields_ = [("time_ms", ct.c_uint64)] + [
        (name, ct.c_uint32) for name in ("type", "index", "value", "reserved")
    ]


class _NamedEvent(ct.Structure):
    _fields_ = [("time_ms", ct.c_uint64)] + [
        (name, ct.c_uint32)
        for name in ("type", "source_index", "value", "reserved")
    ] + [("name", ct.c_char * 64)]


@lru_cache(maxsize=1)
def _native() -> ct.CDLL:
    override = os.environ.get("WOLFEYE_NATIVE_DIR")
    if override:
        directory = Path(override)
    else:
        root = (
            Path(sys._MEIPASS)
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        directory = root / "native" / "beacheye"
    # Device build numbers select DisablePoints inside the company branch;
    # they must not select a different BeachEye repository branch/DLL.
    path = directory / "wolfeye_beacheye.dll"
    try:
        library = ct.CDLL(str(path))
        library.be_abi_version.argtypes = []
        library.be_abi_version.restype = ct.c_uint32
        if library.be_abi_version() != 12:
            raise ValueError(
                "Unsupported BeachEye bridge ABI; rebuild wolfeye_beacheye.dll"
            )
        for name, output in (
            ("info", _Info),
            ("measurements", _Point),
            ("events", _Event),
        ):
            function = getattr(library, f"be_{name}")
            function.argtypes = [ct.c_void_p, ct.c_size_t, ct.POINTER(output)]
            if name != "info":
                function.argtypes += [ct.c_size_t]
            function.restype = ct.c_int
        library.be_measurements_named.argtypes = [
            ct.c_void_p,
            ct.c_size_t,
            ct.c_uint32,
            ct.c_uint32,
            ct.POINTER(_NamedPoint),
            ct.c_size_t,
        ]
        library.be_measurements_named.restype = ct.c_int
        library.be_events_named.argtypes = [
            ct.c_void_p,
            ct.c_size_t,
            ct.c_uint32,
            ct.c_uint32,
            ct.POINTER(_NamedEvent),
            ct.c_size_t,
        ]
        library.be_events_named.restype = ct.c_int
        library.be_frame_build.argtypes = [
            ct.c_uint8,
            ct.c_void_p,
            ct.c_size_t,
            ct.c_void_p,
            ct.c_size_t,
        ]
        library.be_frame_build.restype = ct.c_int
        library.be_frame_decode.argtypes = [
            ct.c_void_p,
            ct.c_size_t,
            ct.POINTER(ct.c_uint8),
            ct.c_void_p,
            ct.c_size_t,
        ]
        library.be_frame_decode.restype = ct.c_int
        library.be_point_catalog_json.argtypes = [
            ct.c_uint32,
            ct.c_uint32,
            ct.c_void_p,
            ct.c_size_t,
        ]
        library.be_point_catalog_json.restype = ct.c_int
        for name in ("default_json", "payload_json"):
            function = getattr(library, f"be_settings_{name}")
            function.argtypes = (
                [ct.c_uint32, ct.c_void_p, ct.c_size_t]
                if name == "default_json"
                else [ct.c_void_p, ct.c_size_t, ct.c_uint32, ct.c_void_p, ct.c_size_t]
            )
            function.restype = ct.c_int
        library.be_settings_default_file.argtypes = [
            ct.c_uint32,
            ct.c_void_p,
            ct.c_size_t,
        ]
        library.be_settings_default_file.restype = ct.c_int
        library.be_settings_encode_json.argtypes = [
            ct.c_void_p,
            ct.c_size_t,
            ct.c_uint32,
            ct.c_void_p,
            ct.c_size_t,
        ]
        library.be_settings_encode_json.restype = ct.c_int
        library.be_settings_decode_json.argtypes = [
            ct.c_void_p,
            ct.c_size_t,
            ct.c_void_p,
            ct.c_size_t,
        ]
        library.be_settings_decode_json.restype = ct.c_int
        library.be_settings_file_from_payload.argtypes = [
            ct.c_void_p,
            ct.c_size_t,
            ct.c_uint32,
            ct.c_void_p,
            ct.c_size_t,
        ]
        library.be_settings_file_from_payload.restype = ct.c_int
        library.be_settings_patch_payload_json.argtypes = [
            ct.c_void_p,
            ct.c_size_t,
            ct.c_void_p,
            ct.c_size_t,
            ct.c_uint32,
            ct.c_void_p,
            ct.c_size_t,
        ]
        library.be_settings_patch_payload_json.restype = ct.c_int
        library.be_editor_payload_json.argtypes = library.be_settings_payload_json.argtypes
        library.be_editor_payload_json.restype = ct.c_int
        library.be_editor_patch_payload_json.argtypes = library.be_settings_patch_payload_json.argtypes
        library.be_editor_patch_payload_json.restype = ct.c_int
        library.be_provider_create.argtypes = [_ProviderCallback, ct.c_void_p]
        library.be_provider_create.restype = ct.c_void_p
        library.be_provider_destroy.argtypes = [ct.c_void_p]
        library.be_provider_destroy.restype = None
        library.be_provider_start.argtypes = [
            ct.c_void_p,
            ct.c_char_p,
            ct.c_uint16,
            ct.c_uint32,
        ]
        library.be_provider_start.restype = ct.c_int
        library.be_provider_stop.argtypes = [ct.c_void_p]
        library.be_provider_stop.restype = None
        library.be_provider_request.argtypes = [
            ct.c_void_p,
            ct.c_uint32,
            ct.c_uint8,
            ct.c_void_p,
            ct.c_size_t,
        ]
        library.be_provider_request.restype = ct.c_int
        library.be_provider_update_file.argtypes = [
            ct.c_void_p,
            ct.c_uint32,
            ct.c_wchar_p,
            ct.c_uint32,
            ct.c_uint32,
        ]
        library.be_provider_update_file.restype = ct.c_int
    except (OSError, AttributeError) as exc:
        raise ValueError(
            f"Cannot load BeachEye C++ bridge: {path}. Build the DLL for this Python architecture. {exc}"
        ) from exc
    return library


class NativeDataProvider:
    """Thin Python binding; TCP, framing, sequencing and updates stay in C++."""

    def __init__(
        self, callback: Callable[[int, int, int, bytes], None]
    ) -> None:
        self._on_event = callback
        self._last_error = ""

        @_ProviderCallback
        def receive(
            _context: int,
            event: int,
            tag: int,
            value: int,
            data: int,
            size: int,
        ) -> None:
            payload = ct.string_at(data, size) if data and size else b""
            if event == PROVIDER_ERROR:
                self._last_error = payload.decode("utf-8", errors="replace")
            self._on_event(event, tag, value, payload)

        self._callback = receive
        self._handle = _native().be_provider_create(self._callback, None)
        if not self._handle:
            raise ValueError("Cannot create the native BeachEye DataProvider")

    def start(
        self,
        ip: str,
        port: int = 6536,
        timeout_ms: int = 5000,
    ) -> None:
        self._last_error = ""
        if _native().be_provider_start(
            self._handle,
            ip.encode("ascii"),
            port,
            timeout_ms,
        ) < 0:
            raise OSError(self._last_error or "Native TCP connection failed")

    def stop(self) -> None:
        if self._handle:
            _native().be_provider_stop(self._handle)

    def request(self, tag: int, frame_type: int, payload: bytes = b"") -> None:
        self._last_error = ""
        source = ct.create_string_buffer(payload) if payload else None
        if _native().be_provider_request(
            self._handle, tag, frame_type, source, len(payload)
        ) < 0:
            raise OSError(self._last_error or "Native DataProvider rejected the request")

    def update_file(
        self, kind: int, path: str, hardware: int, bootloader: int
    ) -> None:
        if _native().be_provider_update_file(
            self._handle, kind, path, hardware, bootloader
        ) < 0:
            raise ValueError("Native DataProvider rejected the update file")

    def close(self) -> None:
        if self._handle:
            handle, self._handle = self._handle, None
            _native().be_provider_destroy(handle)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _decode(name: str, payload: bytes, output: object, *args: int) -> int:
    buffer = ct.create_string_buffer(payload)
    count = getattr(_native(), f"be_{name}")(buffer, len(payload), output, *args)
    if count < 0:
        raise ValueError(
            f"Invalid or incomplete BeachEye {name} payload ({len(payload)} bytes)"
        )
    return count


def decode_info(payload: bytes) -> dict[str, object]:
    info = _Info()
    _decode("info", payload, ct.byref(info))
    return {
        "model": {1: "FC22AR", 2: "FC22S"}.get(info.model, f"Unknown ({info.model})"),
        **{
            name: getattr(info, name)
            for name in ("firmware", "hardware", "bootloader", "build", "flags")
        },
        "commit": bytes(info.commit).rstrip(b"\0").decode("ascii", errors="replace"),
    }


def decode_measurements(
    payload: bytes, model: str = "", build: int = 0
) -> MeasurementSnapshot:
    """Decode the self-describing measurement blocks used by DataProvider.

    The named bridge provides the model/revision-specific ordering used by the
    company UI when the point counts match. Other complete blocks retain their
    wire indices instead of rejecting a valid response or borrowing names from
    a different revision.
    """
    if not _model_code(model):
        return _decode_measurements_by_wire_schema(payload)
    points = (_NamedPoint * max(1, len(payload) * 8))()
    buffer = ct.create_string_buffer(payload)
    count = _native().be_measurements_named(
        buffer,
        len(payload),
        _model_code(model),
        build,
        points,
        len(points),
    )
    if count < 0:
        return _decode_measurements_by_wire_schema(payload)
    analog: dict[str, float] = {}
    binary: dict[str, bool] = {}
    counters: dict[str, int] = {}
    analog_indices: dict[str, int] = {}
    binary_indices: dict[str, int] = {}
    for i in range(count):
        point = points[i]
        name = _native_name(point.name, point.type, point.source_index)
        if point.type == M_TYPE_BI:
            key = _put_unique(binary, name, bool(point.value), point.source_index)
            binary_indices[key] = int(point.dnp_index)
        elif point.type == M_TYPE_AI:
            key = _put_unique(analog, name, float(point.value), point.source_index)
            analog_indices[key] = int(point.dnp_index)
        else:
            _put_unique(counters, name, int(point.value), point.source_index)
    return MeasurementSnapshot(analog, binary, counters, analog_indices=analog_indices, binary_indices=binary_indices)


def _decode_measurements_by_wire_schema(payload: bytes) -> MeasurementSnapshot:
    """Use BeachEye's header/count parser when a revision table does not match."""
    points = (_Point * max(1, len(payload) * 8))()
    count = _decode("measurements", payload, points, len(points))
    analog: dict[str, float] = {}
    binary: dict[str, bool] = {}
    counters: dict[str, int] = {}
    # This path accepts complete blocks with an unrecognized point map. Never borrow
    # labels from another revision: a plausible but incorrect name is worse
    # than an explicit generic index for protection measurements.
    for i in range(count):
        point = points[i]
        prefix = (
            "BI"
            if point.type == M_TYPE_BI
            else "AI"
            if point.type == M_TYPE_AI
            else "Counter"
        )
        name = f"{prefix} {point.index}"
        if point.type == M_TYPE_BI:
            _put_unique(binary, name, bool(point.value), point.index)
        elif point.type == M_TYPE_AI:
            _put_unique(analog, name, float(point.value), point.index)
        elif point.type == M_TYPE_BC:
            _put_unique(counters, name, int(point.value), point.index)
    return MeasurementSnapshot(analog, binary, counters)


def decode_events(
    payload: bytes, model: str = "", build: int = 0
) -> list[EventRecord]:
    events = (_NamedEvent * max(1, len(payload) // 8))()
    buffer = ct.create_string_buffer(payload)
    count = _native().be_events_named(
        buffer,
        len(payload),
        _model_code(model),
        build,
        events,
        len(events),
    )
    if count < 0:
        raise ValueError(f"Invalid or incomplete BeachEye events payload ({len(payload)} bytes)")
    records = []
    invalid_timestamps = 0
    for i in range(count):
        event = events[i]
        # Company EventToString omits zero-time events.
        if not event.time_ms:
            continue
        try:
            # DataProvider::EventToString subtracts the fixed device offset
            # before converting to local time.
            timestamp = datetime.fromtimestamp(
                (event.time_ms - EVENT_TIMEZONE_OFFSET_MS) / 1000
            )
        except (OSError, OverflowError, ValueError):
            invalid_timestamps += 1
            continue
        binary = event.type == 0
        category = "Binary" if binary else "Analog" if event.type == 1 else "Counter"
        records.append(
            EventRecord(
                timestamp,
                category,
                _native_name(event.name, event.type, event.source_index),
                ("ON" if event.value else "OFF") if binary else str(event.value),
                int(event.reserved),
            )
        )
    if count and not records and invalid_timestamps:
        raise ValueError("BeachEye event response contains no valid timestamps")
    return records


def build_native_frame(frame_type: int, payload: bytes = b"") -> bytes:
    if not 0 <= frame_type <= 0xFF:
        raise ValueError("frame_type must fit in one byte")
    if len(payload) > 0xFFFF:
        raise ValueError("Frame data does not fit the protocol's two-byte length field")
    source = ct.create_string_buffer(payload)
    output = (ct.c_ubyte * (len(payload) + 7))()
    size = _native().be_frame_build(frame_type, source, len(payload), output, len(output))
    if size < 0:
        raise ValueError("The native bridge could not build the frame")
    return bytes(output[:size])


def decode_native_frame(frame: bytes) -> tuple[int, bytes]:
    source = ct.create_string_buffer(frame)
    frame_type = ct.c_uint8()
    capacity = max(1, len(frame) - 7)
    payload = (ct.c_ubyte * capacity)()
    size = _native().be_frame_decode(
        source, len(frame), ct.byref(frame_type), payload, capacity
    )
    if size < 0:
        raise ValueError("Invalid WolfEye frame or CRC")
    return frame_type.value, bytes(payload[:size])


def default_settings_json(model: str) -> dict[str, object]:
    """Return defaults produced by the original C++ Settings implementation."""
    output = ct.create_string_buffer(1_048_576)
    size = _native().be_settings_default_json(_model_code(model), output, len(output))
    return _settings_json_result(size, output, "create default settings")


def settings_point_catalog(
    model: str = "FC22AR", build: int = 50
) -> dict[str, tuple[tuple[int, str], ...]]:
    """Return the exact enabled BI/AI operands used by the company function editor."""
    output = ct.create_string_buffer(1_048_576)
    size = _native().be_point_catalog_json(
        _model_code(model), build, output, len(output)
    )
    raw = _settings_json_result(size, output, "read settings point catalog")
    return {
        kind: tuple((int(item["id"]), str(item["name"])) for item in raw[kind])
        for kind in ("binary", "analog")
    }


def default_settings_file(model: str) -> bytes:
    """Serialize original C++ defaults without an intermediate representation."""
    output = (ct.c_ubyte * 1_048_576)()
    size = _native().be_settings_default_file(_model_code(model), output, len(output))
    if size < 0:
        raise ValueError("The native WolfEye defaults could not be serialized")
    return bytes(output[:size])


def decode_settings_payload(payload: bytes, model: str) -> dict[str, object]:
    """Decode a raw device Settings payload through the original C++ code."""
    source = ct.create_string_buffer(payload)
    output = ct.create_string_buffer(1_048_576)
    size = _native().be_settings_payload_json(
        source, len(payload), _model_code(model), output, len(output)
    )
    return _settings_json_result(size, output, "decode device settings")


def encode_settings_file(settings: dict[str, object], model: str) -> bytes:
    """Build the exact WolfEye Settings + device flag + CRC16 .bin layout."""
    encoded = json.dumps(settings, separators=(",", ":")).encode("utf-8")
    source = ct.create_string_buffer(encoded)
    output = (ct.c_ubyte * 1_048_576)()
    size = _native().be_settings_encode_json(
        source, len(encoded), _model_code(model), output, len(output)
    )
    if size < 0:
        raise ValueError("The native WolfEye settings could not be encoded")
    return bytes(output[:size])


def decode_settings_file(data: bytes) -> tuple[dict[str, object], str]:
    """Validate and decode an original WolfEye setup .bin file."""
    if len(data) < 3:
        raise ValueError("The WolfEye setup file is incomplete")
    source = ct.create_string_buffer(data)
    output = ct.create_string_buffer(1_048_576)
    size = _native().be_settings_decode_json(source, len(data), output, len(output))
    settings = _settings_json_result(size, output, "decode setup file")
    return settings, "FC22AR" if data[-3] == 1 else "FC22S"


def settings_file_from_payload(payload: bytes, model: str) -> bytes:
    """Wrap an unmodified device payload exactly like SaveSettingsToFile()."""
    source = ct.create_string_buffer(payload)
    output = (ct.c_ubyte * (len(payload) + 3))()
    size = _native().be_settings_file_from_payload(
        source, len(payload), _model_code(model), output, len(output)
    )
    if size < 0:
        raise ValueError("The payload size does not match the selected WolfEye model")
    return bytes(output[:size])


def patch_settings_payload(
    payload: bytes, settings: dict[str, object], model: str
) -> bytes:
    """Apply JSON with the company importer and serializer."""
    encoded = json.dumps(settings, separators=(",", ":")).encode("utf-8")
    base = ct.create_string_buffer(payload)
    source = ct.create_string_buffer(encoded)
    output = (ct.c_ubyte * len(payload))()
    size = _native().be_settings_patch_payload_json(
        base,
        len(payload),
        source,
        len(encoded),
        _model_code(model),
        output,
        len(output),
    )
    if size < 0:
        raise ValueError("The native WolfEye settings payload could not be patched")
    return bytes(output[:size])


def decode_editor_payload(payload: bytes, model: str) -> dict[str, object]:
    """Read actual Configure fields without the company JSON exporter's mutation."""
    source = ct.create_string_buffer(payload)
    output = ct.create_string_buffer(1_048_576)
    size = _native().be_editor_payload_json(
        source, len(payload), _model_code(model), output, len(output)
    )
    return _settings_json_result(size, output, "read Configure fields")


def patch_editor_payload(payload: bytes, settings: dict[str, object], model: str) -> bytes:
    """Assign typed Configure members, then use the original wire serializer."""
    encoded = json.dumps(settings, separators=(",", ":"), allow_nan=False).encode("utf-8")
    base, source = ct.create_string_buffer(payload), ct.create_string_buffer(encoded)
    output = (ct.c_ubyte * len(payload))()
    size = _native().be_editor_patch_payload_json(
        base, len(payload), source, len(encoded), _model_code(model), output, len(output)
    )
    if size < 0:
        raise ValueError("Invalid Configure field type, range, or payload size")
    return bytes(output[:size])


def default_editor_json(model: str) -> dict[str, object]:
    return decode_editor_payload(default_settings_file(model)[:-3], model)


def encode_editor_file(settings: dict[str, object], model: str) -> bytes:
    payload = patch_editor_payload(default_settings_file(model)[:-3], settings, model)
    return settings_file_from_payload(payload, model)


def decode_editor_file(data: bytes) -> tuple[dict[str, object], str]:
    # Native setup validation checks the model flag, exact payload length and CRC.
    if len(data) < 3:
        raise ValueError("The WolfEye setup file is incomplete")
    model = "FC22AR" if data[-3] == 1 else "FC22S"
    if data[-3] not in (0, 1) or settings_file_from_payload(data[:-3], model) != data:
        raise ValueError("Invalid WolfEye setup length, model flag or CRC")
    return decode_editor_payload(data[:-3], model), model


def _settings_json_result(
    size: int, output: ct.Array[ct.c_char], operation: str
) -> dict[str, object]:
    if size < 0:
        raise ValueError(f"The native WolfEye bridge could not {operation}")
    try:
        value = json.loads(bytes(output.raw[:size]))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The native WolfEye bridge returned invalid settings JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("The native WolfEye bridge returned an invalid settings object")
    return value


def _model_code(model: str) -> int:
    value = normalize_device_model(model)
    return 1 if value == "FC22AR" else 2 if value == "FC22S" else 0


def normalize_device_model(model: object) -> str:
    """Return the two model identifiers used by the company point profiles."""
    text = str(model or "").strip()
    compact = re.sub(r"[^A-Z0-9]", "", text.upper())
    if compact == "FC22S" or "SECTIONALIZER" in compact:
        return "FC22S"
    if compact == "FC22AR" or "AUTORECLOSER" in compact or "RECLOSER" in compact:
        return "FC22AR"
    return text or "WolfEye"


def normalize_device_revision(revision: object) -> int:
    """Parse revision values such as 50, V50, Revision 51, or 1.3.51."""
    if isinstance(revision, bool):
        return 0
    if isinstance(revision, int):
        return max(0, revision)
    matches = re.findall(r"\d+", str(revision or ""))
    return int(matches[-1]) if matches else 0


def _native_name(raw: bytes, point_type: int, source_index: int) -> str:
    name = bytes(raw).split(b"\0", 1)[0].decode("utf-8", errors="replace")
    if name:
        return name
    return f"{'BI' if point_type == M_TYPE_BI else 'AI' if point_type == M_TYPE_AI else 'Counter'} {source_index}"


_Value = TypeVar("_Value")


def _put_unique(
    values: dict[str, _Value], name: str, value: _Value, source_index: int
) -> str:
    key = name if name not in values else f"{name} [{source_index}]"
    values[key] = value
    return key
