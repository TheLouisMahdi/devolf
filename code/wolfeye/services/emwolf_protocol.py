"""EmWolf scenario validation, wire encoding, and connection handling."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import math
import secrets
from datetime import datetime
import socket
import select
import struct
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from wolfeye.services.emwolf_run import RunCache, ReceiptLease, EVENT, STATUS, EVENT_LIMIT, CHUNK_LIMIT, TERMINAL, STATE_NAMES, atomic_json

DEFAULT_HOST = "192.168.137.1"
DEFAULT_PORT = 666
BOARD_SAMPLE_TIME_US = 320
FRAME_START = b"\x41\x24"
PING = 0x00
RESPONSE = 0x01
HEARTBEAT_INTERVAL_S = 5.0
HEARTBEAT_TIMEOUT_S = 15.0
HEARTBEAT_GRACE_S = 5.0
HEARTBEAT_RETRY_INTERVAL_S = 1.0
EW_START = 0x80
EW_RESULT = 0x8D
EW_DI_EVENT = 0x8E
EW_STOP = 0x90
EW_RUN_START = 0x91
EW_RUN_QUERY = 0x92
EW_RUN_FETCH = 0x93
EW_RUN_DATA = 0x94
EW_RUN_RECEIVED = 0x95
EW_RUN_STATUS = 0x96
EW_RUN_STOP = 0x97
EW_RUN_PROJECT = 0x98
EW_STOP_TOKEN = b"STOP"
DI_DEBOUNCE_US = 1_000
DI_TIMESTAMP_MODULUS = 1 << 28
CHANNEL_NAMES = ("Va", "Vb", "Vc", "Vt", "Ia", "Ib", "Ic", "In")
CURRENT_CHANNEL_NAMES = frozenset(("Ia", "Ib", "Ic", "In"))
MAX_CURRENT_AMPLITUDE_A = 0.5
DEFAULT_DIGITAL_INPUT_NAMES = ("DI1", "DI2", "DI3", "DI4")
# DI_TOGGLE completes on either edge and is used for every DI-based scenario.
# Keep its original wire value (0) and the remaining values stable.
END_TYPES = ("DI_TOGGLE", "CYCLES", "TIME", "INFINITE")
MAX_PAYLOAD_SIZE = 5 * 1024
SETUP_WIRE_SIZE = 20
EWS2_HEADER_SIZE = 6
EWS2_SCENARIO_SIZE = 171
MAX_SCENARIOS = (
    MAX_PAYLOAD_SIZE - SETUP_WIRE_SIZE - EWS2_HEADER_SIZE
) // EWS2_SCENARIO_SIZE


def crc_ccitt(data: bytes) -> int:
    """CRC-CCITT/FALSE: polynomial 0x1021, initial value 0xFFFF."""
    remainder = 0xFFFF
    for byte in data:
        remainder ^= byte << 8
        for _ in range(8):
            if remainder & 0x8000:
                remainder = ((remainder << 1) ^ 0x1021) & 0xFFFF
            else:
                remainder = (remainder << 1) & 0xFFFF
    return remainder


def build_frame(frame_type: int, payload: bytes) -> bytes:
    if not 0 <= frame_type <= 0xFF:
        raise ValueError("Frame type must fit in one byte")
    if len(payload) > 0xFFFF:
        raise ValueError("Payload is too large")
    body = struct.pack("<HB", len(payload), frame_type) + payload
    return FRAME_START + body + struct.pack("<H", crc_ccitt(body))


class FrameDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> Iterable[tuple[int, bytes]]:
        self._buffer.extend(data)
        frames: list[tuple[int, bytes]] = []
        while True:
            start = self._buffer.find(FRAME_START)
            if start < 0:
                self._buffer[:] = self._buffer[-1:]
                break
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 7:
                break
            payload_size = struct.unpack_from("<H", self._buffer, 2)[0]
            if payload_size > MAX_PAYLOAD_SIZE:
                del self._buffer[:2]
                continue
            frame_size = payload_size + 7
            if len(self._buffer) < frame_size:
                break
            candidate = bytes(self._buffer[:frame_size])
            del self._buffer[:frame_size]
            expected_crc = struct.unpack_from("<H", candidate, frame_size - 2)[0]
            calculated_crc = crc_ccitt(candidate[2:-2])
            if expected_crc != calculated_crc:
                continue
            frames.append((candidate[4], candidate[5:-2]))
        return frames


@dataclass
class AnalogOutput:
    enabled: bool = False
    amplitude: float = 0.0
    frequency: float = 50.0
    phase: int = 0
    harmonic1_order: int = 2
    harmonic1_amplitude: float = 0.0
    harmonic2_order: int = 2
    harmonic2_amplitude: float = 0.0

    @classmethod
    def from_dict(cls, value: dict) -> AnalogOutput:
        known = {item.name for item in cls.__dataclass_fields__.values()}
        return cls(**{key: item for key, item in value.items() if key in known})

    def validate(self, channel_name: str) -> None:
        numeric_values = (
            self.amplitude,
            self.frequency,
            self.harmonic1_amplitude,
            self.harmonic2_amplitude,
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise ValueError(f"{channel_name}: values must be finite")
        if self.frequency <= 0:
            raise ValueError(f"{channel_name}: frequency must be greater than zero")
        if not 0 <= self.phase <= 359:
            raise ValueError(f"{channel_name}: phase must be 0..359 degrees")
        for order in (self.harmonic1_order, self.harmonic2_order):
            if not 2 <= order <= 15:
                raise ValueError(f"{channel_name}: harmonic order must be 2..15")
        if channel_name in CURRENT_CHANNEL_NAMES:
            maximum_instantaneous_amplitude = sum(
                abs(value)
                for value in (
                    self.amplitude,
                    self.harmonic1_amplitude,
                    self.harmonic2_amplitude,
                )
            )
            if maximum_instantaneous_amplitude > MAX_CURRENT_AMPLITUDE_A + 1e-9:
                raise ValueError(
                    f"{channel_name}: total current amplitude must not exceed "
                    f"{MAX_CURRENT_AMPLITUDE_A:g} A"
                )

    def serialize(self) -> bytes:
        amplitude = self.amplitude if self.enabled else 0.0
        harmonic1 = self.harmonic1_amplitude if self.enabled else 0.0
        harmonic2 = self.harmonic2_amplitude if self.enabled else 0.0
        return struct.pack(
            "<ffffHBB",
            amplitude,
            self.frequency,
            harmonic1,
            harmonic2,
            self.phase,
            self.harmonic1_order - 2,
            self.harmonic2_order - 2,
        )


def default_analogs() -> dict[str, AnalogOutput]:
    return {name: AnalogOutput() for name in CHANNEL_NAMES}


@dataclass
class Scenario:
    name: str = "Scenario #1"
    analogs: dict[str, AnalogOutput] = field(default_factory=default_analogs)
    digital_outputs: list[bool] = field(default_factory=lambda: [False] * 4)
    end_type: str = "CYCLES"
    digital_input: int = 1
    end_value: float = 1.0

    @classmethod
    def from_dict(cls, value: dict) -> Scenario:
        analog_data = value.get("analogs", {})
        analogs = {
            name: AnalogOutput.from_dict(analog_data.get(name, {}))
            for name in CHANNEL_NAMES
        }
        outputs = list(value.get("digital_outputs", [False] * 4))[:4]
        outputs.extend([False] * (4 - len(outputs)))
        end_type = str(value.get("end_type", "CYCLES")).upper()
        if end_type == "DI_FALLING":
            end_type = "DI_TOGGLE"
        return cls(
            name=str(value.get("name", "Scenario")),
            analogs=analogs,
            digital_outputs=[bool(item) for item in outputs],
            end_type=end_type,
            digital_input=int(value.get("digital_input", 1)),
            end_value=float(value.get("end_value", 1.0)),
        )

    def validate(self) -> None:
        for name in CHANNEL_NAMES:
            self.analogs[name].validate(name)
        if len(self.digital_outputs) != 4:
            raise ValueError(f"{self.name}: exactly four digital outputs are required")
        if self.end_type not in END_TYPES:
            raise ValueError(f"{self.name}: unsupported end type {self.end_type}")
        if not 1 <= self.digital_input <= 4:
            raise ValueError(f"{self.name}: digital input must be 1..4")
        if not math.isfinite(self.end_value) or self.end_value < 0:
            raise ValueError(f"{self.name}: end value must be finite and non-negative")

    def serialize(self) -> bytes:
        self.validate()
        result = bytearray()
        for name in CHANNEL_NAMES:
            result.extend(self.analogs[name].serialize())

        digital_mask = sum(
            (1 << index)
            for index, enabled in enumerate(self.digital_outputs)
            if enabled
        )
        result.append(digital_mask)

        end_type = END_TYPES.index(self.end_type)
        if self.end_type == "TIME":
            protocol_value = round(self.end_value * 1000.0)
        elif self.end_type == "CYCLES":
            protocol_value = round(self.end_value)
        else:
            protocol_value = 0
        if not 0 <= protocol_value <= 0xFFFFFFFF:
            raise ValueError(f"{self.name}: end value exceeds the protocol range")

        result.extend(
            struct.pack(
                "<BBII",
                end_type,
                self.digital_input - 1,
                protocol_value,
                0,
            )
        )
        if len(result) != EWS2_SCENARIO_SIZE:
            raise AssertionError("Unexpected EWS2 scenario size")
        return bytes(result)


def emwolf_default_scenario(name: str = "EmWolf default") -> Scenario:
    analogs = default_analogs()
    defaults = {
        "Va": (1.0, 0),
        "Vb": (1.5, 120),
        "Vc": (2.0, 240),
        "Vt": (2.5, 0),
        "Ia": (0.2, 0),
        "Ib": (0.3, 120),
        "Ic": (0.4, 240),
        "In": (0.2, 0),
    }
    for channel_name, (amplitude, phase) in defaults.items():
        analogs[channel_name] = AnalogOutput(
            enabled=True,
            amplitude=amplitude,
            frequency=50.0,
            phase=phase,
        )
    return Scenario(
        name=name,
        analogs=analogs,
        digital_outputs=[False] * 4,
        end_type="INFINITE",
        end_value=float(0xFFFFFFFF),
    )


@dataclass
class Setup:
    offsets: dict[str, int] = field(
        default_factory=lambda: {name: 2048 for name in CHANNEL_NAMES}
    )
    sample_time_us: float = BOARD_SAMPLE_TIME_US
    digital_input_names: list[str] = field(
        default_factory=lambda: list(DEFAULT_DIGITAL_INPUT_NAMES)
    )

    @classmethod
    def from_dict(cls, value: dict) -> Setup:
        source_offsets = value.get("offsets", {})
        offsets = {name: int(source_offsets.get(name, 2048)) for name in CHANNEL_NAMES}
        source_names = list(value.get("digital_input_names", DEFAULT_DIGITAL_INPUT_NAMES))[:4]
        source_names.extend(DEFAULT_DIGITAL_INPUT_NAMES[len(source_names):])
        return cls(
            offsets=offsets,
            sample_time_us=float(value.get("sample_time_us", BOARD_SAMPLE_TIME_US)),
            digital_input_names=[str(name).strip() for name in source_names],
        )

    def validate(self) -> None:
        if not math.isfinite(self.sample_time_us) or self.sample_time_us <= 0:
            raise ValueError("Sample time must be finite and greater than zero")
        for name, value in self.offsets.items():
            if not 0 <= value <= 0xFFFF:
                raise ValueError(f"{name} offset must be 0..65535")
        if len(self.digital_input_names) != 4:
            raise ValueError("Exactly four digital input names are required")
        for input_id, name in enumerate(self.digital_input_names, 1):
            if not name.strip():
                raise ValueError(f"Digital input {input_id} name must not be empty")
            if len(name) > 32:
                raise ValueError(f"Digital input {input_id} name must be at most 32 characters")

    def digital_input_name(self, input_id: int) -> str:
        if not 1 <= input_id <= len(self.digital_input_names):
            raise ValueError("Digital input must be 1..4")
        return self.digital_input_names[input_id - 1].strip()

    def serialize(self) -> bytes:
        self.validate()
        return struct.pack(
            "<8Hf",
            *(self.offsets[name] for name in CHANNEL_NAMES),
            self.sample_time_us,
        )


@dataclass
class DeviceMetadata:
    """Last device identity read by WolfEye over the LAN connection."""

    model: str = ""
    ip: str = ""
    firmware: int = 0
    hardware: int = 0
    build: int = 0
    transport: str = ""

    @classmethod
    def from_dict(cls, value: dict) -> DeviceMetadata:
        return cls(
            model=str(value.get("model", "")).strip(),
            ip=str(value.get("ip", "")).strip(),
            firmware=int(value.get("firmware", 0)),
            hardware=int(value.get("hardware", 0)),
            build=int(value.get("build", 0)),
            transport=str(value.get("transport", "")).strip(),
        )

    @property
    def available(self) -> bool:
        return bool(self.model and self.model != "—")


@dataclass
class Project:
    setup: Setup = field(default_factory=Setup)
    scenarios: list[Scenario] = field(default_factory=lambda: [Scenario()])
    device: DeviceMetadata = field(default_factory=DeviceMetadata)

    @classmethod
    def from_dict(cls, value: dict) -> Project:
        scenarios = [Scenario.from_dict(item) for item in value.get("scenarios", [])]
        return cls(
            setup=Setup.from_dict(value.get("setup", {})),
            scenarios=scenarios,
            device=DeviceMetadata.from_dict(value.get("device", {})),
        )

    def validate(self) -> None:
        self.setup.validate()
        if not self.scenarios:
            raise ValueError("At least one scenario is required")
        if len(self.scenarios) > MAX_SCENARIOS:
            raise ValueError(f"At most {MAX_SCENARIOS} scenarios fit in one frame")
        for scenario in self.scenarios:
            scenario.validate()

    def build_payload(self) -> bytes:
        self.validate()
        payload = bytearray(self.setup.serialize())
        payload.extend(b"EWS2")
        payload.extend(struct.pack("<H", len(self.scenarios)))
        for scenario in self.scenarios:
            payload.extend(scenario.serialize())
        if len(payload) > MAX_PAYLOAD_SIZE:
            raise ValueError("Scenario payload exceeds the LightStream limit")
        return bytes(payload)

    def build_frame(self) -> bytes:
        return build_frame(EW_START, self.build_payload())


def load_project(path: Path) -> Project:
    with path.open("r", encoding="utf-8") as source:
        return Project.from_dict(json.load(source))


def save_project(path: Path, project: Project) -> None:
    project.validate()
    with path.open("w", encoding="utf-8") as target:
        json.dump(asdict(project), target, indent=2)
        target.write("\n")


def decode_result(payload: bytes) -> tuple[int, bool, int]:
    if len(payload) != 4:
        raise ValueError("EW_RESULT payload must contain four bytes")
    packed = struct.unpack("<I", payload)[0]
    input_id = packed & 0x07
    value = bool((packed >> 3) & 0x01)
    elapsed_us = (packed >> 4) & 0x0FFFFFFF
    if not 1 <= input_id <= 4:
        raise ValueError("EW_RESULT contains an invalid DI identifier")
    return input_id, value, elapsed_us


def decode_di_event(payload: bytes) -> tuple[int, bool, int]:
    if len(payload) != 4:
        raise ValueError("EW_DI_EVENT payload must contain four bytes")
    packed = struct.unpack("<I", payload)[0]
    wire_input_id = packed & 0x07
    value = bool((packed >> 3) & 0x01)
    elapsed_us = (packed >> 4) & 0x0FFFFFFF
    if not 0 <= wire_input_id <= 3:
        raise ValueError("EW_DI_EVENT contains an invalid DI identifier")
    return wire_input_id + 1, value, elapsed_us


class DIEventDebouncer:
    """Reject duplicate/chattering edges while preserving the board timestamp."""

    def __init__(self, debounce_us: int = DI_DEBOUNCE_US) -> None:
        self.debounce_us = debounce_us
        self._accepted: dict[int, tuple[bool, int]] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._accepted.clear()

    def accept(self, input_id: int, value: bool, timestamp_us: int) -> int | None:
        """Return the original board timestamp, or None for a rejected edge."""
        if not 1 <= input_id <= 4:
            raise ValueError("Digital input must be 1..4")
        timestamp_us %= DI_TIMESTAMP_MODULUS
        with self._lock:
            previous = self._accepted.get(input_id)
            if previous is None:
                self._accepted[input_id] = (value, timestamp_us)
                return timestamp_us

            previous_value, previous_timestamp = previous
            if value == previous_value:
                return None

            delta_us = (timestamp_us - previous_timestamp) % DI_TIMESTAMP_MODULUS
            if delta_us <= self.debounce_us:
                return None

            self._accepted[input_id] = (value, timestamp_us)
            return timestamp_us


def project_from_wire(payload: bytes) -> Project:
    if len(payload)<26 or payload[20:24]!=b"EWS2":
        raise ValueError("Invalid saved EmWolf project")
    count=struct.unpack_from("<H",payload,24)[0]
    if not 1<=count<=MAX_SCENARIOS or len(payload)!=26+count*EWS2_SCENARIO_SIZE:
        raise ValueError("Invalid saved EmWolf scenario bounds")
    setup=struct.unpack_from("<8Hf",payload)
    project=Project(setup=Setup(dict(zip(CHANNEL_NAMES,setup[:8])),setup[8]),scenarios=[])
    offset=26
    for index in range(count):
        analogs={}
        for name in CHANNEL_NAMES:
            amplitude,frequency,h1,h2,phase,o1,o2=struct.unpack_from("<ffffHBB",payload,offset)
            offset+=20
            analogs[name]=AnalogOutput(enabled=bool(amplitude or h1 or h2),amplitude=amplitude,frequency=frequency,phase=phase,
                harmonic1_order=o1+2,harmonic1_amplitude=h1,harmonic2_order=o2+2,harmonic2_amplitude=h2)
        mask=payload[offset];offset+=1
        kind,di,value,delay=struct.unpack_from("<BBII",payload,offset);offset+=10
        if kind>=len(END_TYPES) or delay:
            raise ValueError("Unsupported saved EmWolf end condition")
        project.scenarios.append(Scenario(name=f"Recovered scenario #{index+1}",analogs=analogs,
            digital_outputs=[bool(mask&(1<<i)) for i in range(4)],end_type=END_TYPES[kind],digital_input=di+1,
            end_value=value/1000 if kind==2 else float(value)))
    project.validate()
    return project


class EmWolfConnection:
    def __init__(
        self,
        on_log: Callable[[str], None],
        on_result: Callable[[int, bool, int], None],
        on_state: Callable[[bool], None],
        on_trip: Callable[[int, bool, int], None] | None = None,
        *, autonomous_enabled: bool = False,
        on_run_state: Callable[[dict], None] | None = None,
        on_run_event: Callable[[dict], None] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._on_log = on_log
        self._on_result = on_result
        self._on_state = on_state
        self._on_trip = on_trip or (lambda _input_id, _value, _elapsed_us: None)
        self._socket: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._disconnect_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._di_debouncer = DIEventDebouncer()
        self._last_di_event: tuple[int, bool, int] | None = None
        self._autonomous_enabled=autonomous_enabled
        self._on_run_state=on_run_state or (lambda _state: None)
        self._on_run_event=on_run_event or (lambda _event: None)
        self._cache_root=cache_dir
        self._cache_directory: Path | None=None
        self._run_cache: RunCache | None=None
        self._run_lock=threading.RLock()
        self._run_snapshot: dict={}
        self._next_run_query=0.0
        self._fetch_pending_until=0.0

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._socket is not None

    def connect(self, host: str, port: int) -> None:
        if self.connected or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._disconnect_requested.clear()
        self._thread = threading.Thread(
            target=self._run, args=(host, port), daemon=True
        )
        self._thread.start()

    def _run(self, host: str, port: int) -> None:
        connection: socket.socket | None = None
        lease: ReceiptLease | None = None
        try:
            if self._autonomous_enabled:
                self._cache_directory=RunCache.directory_for(host,port,self._cache_root)
                lease=ReceiptLease(self._cache_directory)
                with self._run_lock:
                    self._run_cache=RunCache.load_active(self._cache_directory)
                    self._run_snapshot={}
                    self._fetch_pending_until=0.0
            self._on_log(f"Connecting to {host}:{port}...")
            connection = socket.create_connection((host, port), timeout=5.0)
            connection.settimeout(0.5)
            with self._lock:
                if self._stop.is_set():
                    return
                self._socket = connection
            self._on_state(True)
            self._on_log("Connected")
            self._di_debouncer.reset()
            self._last_di_event = None
            if self._autonomous_enabled:
                self._restore_cached_run()
                self._query_run()
                self._next_run_query=time.monotonic()+1.0

            decoder = FrameDecoder()
            next_ping = time.monotonic() + HEARTBEAT_INTERVAL_S
            pending_ping: bytes | None = None
            ping_sent_at = 0.0
            ping_sequence = 0
            next_ping_retry = 0.0
            heartbeat_retrying = False
            heartbeat_final_read = False
            while not self._stop.is_set():
                now = time.monotonic()
                if self._autonomous_enabled and now>=self._next_run_query:
                    self._query_run()
                    self._next_run_query=now+1.0
                # Retries never move this deadline or restart the scenario.
                if pending_ping is not None and now - ping_sent_at >= HEARTBEAT_TIMEOUT_S + HEARTBEAT_GRACE_S:
                    # A delayed reader may already have the matching PONG queued.
                    # Drain one ready read before STOP, without waiting or moving
                    # the deadline. Unrelated traffic cannot extend this check.
                    if not heartbeat_final_read and select.select([connection], [], [], 0)[0]:
                        heartbeat_final_read = True
                    else:
                        if not self._autonomous_enabled:
                            # Legacy runs retain their connection-loss Safe Stop.
                            try:
                                with self._send_lock:
                                    connection.sendall(build_frame(EW_STOP, EW_STOP_TOKEN))
                            except OSError:
                                pass
                        else:
                            self._on_log("Communication lost; autonomous execution and durable results remain on the board")
                        raise TimeoutError("EmWolf heartbeat reply timed out after recovery grace; disconnecting")
                if (pending_ping is not None and not heartbeat_final_read
                        and now - ping_sent_at >= HEARTBEAT_TIMEOUT_S
                        and now >= next_ping_retry):
                    if not heartbeat_retrying:
                        self._on_log("Heartbeat reply delayed; retrying the same TCP connection for up to 5 s")
                        heartbeat_retrying = True
                    with self._send_lock:
                        if self._stop.is_set() or self._disconnect_requested.is_set():
                            break
                        connection.sendall(build_frame(PING, pending_ping))
                    next_ping_retry = time.monotonic() + HEARTBEAT_RETRY_INTERVAL_S
                if pending_ping is None and now >= next_ping:
                    ping_sequence = (ping_sequence + 1) & 0xFF
                    pending_ping = bytes([ping_sequence])
                    with self._send_lock:
                        if self._stop.is_set() or self._disconnect_requested.is_set():
                            break
                        connection.sendall(build_frame(PING, pending_ping))
                    ping_sent_at = time.monotonic()
                try:
                    received = connection.recv(4096)
                except socket.timeout:
                    continue
                if not received:
                    break
                for frame_type, payload in decoder.feed(received):
                    if self._autonomous_enabled and frame_type in (EW_RUN_STATUS,EW_RUN_DATA,EW_RUN_PROJECT):
                        self._handle_run_frame(frame_type,payload)
                        continue
                    if frame_type == RESPONSE and pending_ping is not None and payload == pending_ping + b"\x00":
                        if heartbeat_retrying:
                            self._on_log("Heartbeat recovered on the same TCP connection")
                        heartbeat_retrying = False
                        heartbeat_final_read = False
                        next_ping_retry = 0.0
                        pending_ping = None
                        next_ping = time.monotonic() + HEARTBEAT_INTERVAL_S
                        continue
                    if self._autonomous_enabled and frame_type in (EW_RESULT,EW_DI_EVENT):
                        continue  # Unindexed legacy telemetry cannot be assigned to an autonomous stage.
                    if frame_type == EW_RESULT:
                        try:
                            result = decode_result(payload)
                            if result != self._last_di_event:
                                self._on_result(*result)
                            self._on_trip(*result)
                            self._last_di_event = None
                        except ValueError as error:
                            self._on_log(str(error))
                    elif frame_type == EW_DI_EVENT:
                        try:
                            decoded = decode_di_event(payload)
                            elapsed_us = self._di_debouncer.accept(*decoded)
                            if elapsed_us is not None:
                                event = (decoded[0], decoded[1], elapsed_us)
                                self._last_di_event = event
                                self._on_result(*event)
                        except ValueError as error:
                            self._on_log(str(error))
                    else:
                        self._on_log(
                            f"Received frame type 0x{frame_type:02X}, {len(payload)} bytes"
                        )
        except (OSError,ValueError) as error:
            # A local Disconnect deliberately shuts the socket down while the
            # reader thread may still be inside recv(). Do not report that
            # expected wake-up as a connection failure.
            if not self._stop.is_set() and not self._disconnect_requested.is_set():
                self._on_log(f"Connection error: {error}")
        finally:
            if connection is not None:
                try:
                    with self._send_lock:
                        connection.close()
                except OSError:
                    pass
            with self._lock:
                self._socket = None
            if lease is not None:
                with self._run_lock: lease.close()
            self._on_state(False)
            self._on_log("Disconnected")

    def send_project(self, project: Project) -> None:
        payload = project.build_payload()
        frame = build_frame(EW_START, payload)
        with self._lock:
            connection = self._socket
        if connection is None:
            raise ConnectionError("Not connected to EmWolf")
        if self._autonomous_enabled:
            self._send_autonomous(project,payload)
            return
        self._di_debouncer.reset()
        self._last_di_event = None
        with self._send_lock:
            if self._disconnect_requested.is_set() or self._stop.is_set():
                raise ConnectionError("EmWolf is disconnecting")
            connection.sendall(frame)
        self._on_log(
            f"Sent {len(project.scenarios)} scenario(s), payload={len(payload)} bytes"
        )

    def disconnect(self) -> None:
        self._disconnect_requested.set()
        with self._lock:
            connection = self._socket
        if connection is not None:
            try:
                if not self._autonomous_enabled:
                    with self._send_lock:
                        connection.sendall(build_frame(EW_STOP, EW_STOP_TOKEN))
                    self._on_log("Safe stop requested")
                else:
                    self._on_log("Detaching from EmWolf; use Stop test to stop an autonomous run")
            except OSError as error:
                self._on_log(f"Could not send safe stop: {error}")
            self._stop.set()
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        else:
            self._stop.set()


    def _send_control(self,kind: int,payload: bytes) -> None:
        with self._lock: connection=self._socket
        if connection is None: raise ConnectionError("Not connected to EmWolf")
        with self._send_lock:
            if self._stop.is_set() or self._disconnect_requested.is_set():
                raise ConnectionError("EmWolf is disconnecting")
            connection.sendall(build_frame(kind,payload))

    @property
    def results_directory(self) -> Path | None:
        return self._cache_directory

    def request_results(self) -> None:
        """Refresh/resume the stored run without sending a scenario or STOP."""
        if not self._autonomous_enabled:
            raise ValueError("Stored results require autonomous EmWolf mode")
        self._query_run()
        self._on_log("Receiving stored EmWolf results; the accepted run is unchanged")

    def export_results(self, output_path: Path) -> None:
        """Export an immutable PC receipt snapshot; never acknowledge via export."""
        output_path=Path(output_path).resolve()
        with self._run_lock:
            cache=self._run_cache
            if cache is None:
                raise ValueError("No stored EmWolf results; use Receive results first")
            receipt_directory=cache.directory.resolve()
            if output_path==receipt_directory or receipt_directory in output_path.parents:
                raise ValueError("Choose an export location outside the protected EmWolf receipt folder")
            info=self._run_snapshot if self._run_snapshot.get("id")==cache.id else {}
            state=info.get("state",cache.meta.get("state",1))
            expected=info.get("count")
            received=bool(cache.meta.get("collected")) and state in TERMINAL and (expected is None or expected==len(cache.events))
            snapshot=dict(schema="emwolf-results-v1",run_id=f"{cache.id:016x}",
                started_at=cache.meta["started_at"],state=state,state_name=STATE_NAMES.get(state,"UNKNOWN"),
                results_received=received,received_events=len(cache.events),expected_events=expected,
                time_unit="microseconds",scenario_index_base=0,
                event_kinds={1:"scenario_enter",2:"output_applied",3:"digital_input",4:"trip_or_close",5:"scenario_end"},
                project=copy.deepcopy(cache.meta["project"]),events=[event.copy() for event in cache.events])
        descriptor,temp=tempfile.mkstemp(prefix=f".{output_path.name}.",suffix=".tmp",dir=output_path.parent)
        try:
            with os.fdopen(descriptor,"w",encoding="utf-8") as target:
                json.dump(snapshot,target,ensure_ascii=False,indent=2)
                target.flush(); os.fsync(target.fileno())
            os.replace(temp,output_path)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def _query_run(self) -> None:
        with self._run_lock:
            self._send_control(EW_RUN_QUERY,struct.pack("<Q",self._run_cache.id if self._run_cache else 0))

    def _restore_cached_run(self) -> None:
        if self._run_cache is None: return
        self._on_run_state(dict(restore=self._run_cache.meta.copy()))
        for event in self._run_cache.events:
            self._on_run_event(event.copy())

    def _send_autonomous(self,project: Project,payload: bytes) -> None:
        with self._run_lock:
            if self._cache_directory is None: raise ConnectionError("EmWolf connection is not ready")
            snapshot=asdict(project)
            cache=self._run_cache
            if cache is not None and not cache.meta.get("collected"):
                if cache.meta["project"]!=snapshot:
                    raise ValueError("Receive and acknowledge the previous EmWolf run before starting another")
                self._on_log("Retrying the same run ID; an accepted run will not restart")
                self._restore_cached_run()
            else:
                run_id=secrets.randbits(64) or 1
                cache=RunCache.create(self._cache_directory,run_id,snapshot,datetime.now().astimezone().isoformat())
                self._run_cache=cache
                self._run_snapshot={}
                self._restore_cached_run()
            self._send_control(EW_RUN_START,struct.pack("<Q",cache.id)+payload)
            self._next_run_query=0.0
            self._on_log(
                f"Uploaded {len(project.scenarios)} scenarios once (run {cache.id:016x}); "
                "waiting for board acceptance. Results are received automatically."
            )

    def _download_available(self) -> None:
        cache=self._run_cache; info=self._run_snapshot
        if cache is None or info.get("id")!=cache.id: return
        if info["state"] in TERMINAL and len(cache.events)>info["count"]:
            raise ValueError("Board result count regressed; previous PC receipt retained")
        if len(cache.events)<info["count"]:
            if time.monotonic()>=self._fetch_pending_until:
                self._send_control(EW_RUN_FETCH,struct.pack("<QIH",cache.id,len(cache.events)+1,CHUNK_LIMIT))
                self._fetch_pending_until=time.monotonic()+2.0
        elif info["state"] in TERMINAL and info["durable"] and not info["collected"]:
            # append() has fsynced every event before this receipt can be sent.
            cache.status(info["state"],False)
            self._send_control(EW_RUN_RECEIVED,struct.pack("<QI",cache.id,len(cache.events)))

    def _handle_run_frame(self,kind: int,payload: bytes) -> None:
        with self._run_lock:
            if kind==EW_RUN_PROJECT:
                if len(payload)<34: raise ValueError("Invalid saved run project response")
                run_id=struct.unpack_from("<Q",payload)[0]
                if run_id!=self._run_snapshot.get("id"): return
                project=project_from_wire(payload[8:])
                assert self._cache_directory is not None
                path=self._cache_directory/f"{run_id:016x}.json"
                if path.exists():
                    if path.stat().st_size>1024*1024: raise ValueError("Saved EmWolf project exceeds its bound")
                    cache=RunCache(self._cache_directory,json.loads(path.read_text(encoding="utf-8")))
                    if cache.id!=run_id: raise ValueError("Recovered EmWolf metadata ID mismatch")
                    if Project.from_dict(cache.meta["project"]).build_payload()!=payload[8:]:
                        raise ValueError("Saved board parameters conflict with the PC receipt")
                    atomic_json(self._cache_directory/"active.json",dict(id=run_id))
                else:
                    cache=RunCache.create(self._cache_directory,run_id,asdict(project),datetime.now().astimezone().isoformat())
                    self._on_log("Recovered original board parameters; custom scenario names were unavailable")
                self._run_cache=cache
                self._restore_cached_run()
                self._download_available()
                return
            if kind==EW_RUN_STATUS:
                if len(payload)!=STATUS.size: raise ValueError("Invalid EmWolf run status size")
                run_id,state,flags,count,durable_count,scenarios=STATUS.unpack(payload)
                if state not in STATE_NAMES or flags&~3 or count>EVENT_LIMIT or durable_count>count or scenarios>MAX_SCENARIOS:
                    raise ValueError("Invalid EmWolf run status bounds")
                if self._run_cache and run_id and run_id!=self._run_cache.id and self._run_snapshot.get("state") not in (10,12):
                    return  # A queued status from the preceding run must not replace the current report.
                info=dict(id=run_id,state=state,collected=bool(flags&1),durable=bool(flags&2),count=count,durable_count=durable_count,scenarios=scenarios)
                self._run_snapshot=info
                self._on_run_state(dict(info,pc_count=len(self._run_cache.events) if self._run_cache and self._run_cache.id==run_id else 0))
                if state in (9,10,11,12):
                    self._on_log(f"EmWolf run {run_id:016x}: {STATE_NAMES[state]}; previous results are retained")
                    if state in (10,12): self._send_control(EW_RUN_QUERY,struct.pack("<Q",0))
                    if state==9 and run_id and self._run_cache and self._run_cache.id==run_id:
                        self._download_available()  # Preserve readable partial results; never acknowledge a storage failure.
                    return
                if not run_id: return
                if self._run_cache is None or self._run_cache.id!=run_id:
                    self._send_control(EW_RUN_PROJECT,struct.pack("<Q",run_id))
                    return
                was_collected=self._run_cache.meta.get("collected",False)
                self._run_cache.status(state,bool(flags&1) and len(self._run_cache.events)==count)
                if flags&1 and len(self._run_cache.events)==count and not was_collected:
                    self._on_log(f"All {count} EmWolf events are durably received; board receipt confirmed")
                self._download_available()
                return
            if kind==EW_RUN_DATA:
                if len(payload)<14: raise ValueError("Invalid EmWolf event response")
                run_id,first,count=struct.unpack_from("<QIH",payload)
                if count>CHUNK_LIMIT or len(payload)!=14+count*EVENT.size:
                    raise ValueError("Invalid EmWolf event response bounds")
                cache=self._run_cache
                if cache is None or cache.id!=run_id: return
                if not count and first<=self._run_snapshot.get("count",0):
                    raise ValueError("Board returned an empty chunk before all results were received")
                if count and struct.unpack_from("<I",payload,14)[0]!=first:
                    raise ValueError("EmWolf event response starts at the wrong sequence")
                events=cache.append(payload[14:])
                self._fetch_pending_until=0.0
                for event in events: self._on_run_event(event.copy())
                if count: self._download_available()

    def stop_outputs(self) -> None:
        if self._autonomous_enabled:
            with self._run_lock:
                run_id=self._run_cache.id if self._run_cache else self._run_snapshot.get("id",0)
                if run_id:
                    self._send_control(EW_RUN_STOP,struct.pack("<Q",run_id))
                    self._on_log("Explicit stop requested for the autonomous EmWolf run")
                    return
        self._send_control(EW_STOP,EW_STOP_TOKEN)
        self._on_log("Safe stop requested")
