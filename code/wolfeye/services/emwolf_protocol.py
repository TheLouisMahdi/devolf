"""EmWolf scenario validation, wire encoding, and connection handling."""

from __future__ import annotations

import json
import math
import os
import socket
import struct
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_HOST = "192.168.137.1"
DEFAULT_PORT = 666
EMWOLF_SSH_USER = "root"
EMWOLF_REMOTE_COMMAND = "cd /home/FC22 && exec ./EmWolf"
EMWOLF_START_TIMEOUT_S = 8.0
FRAME_START = b"\x41\x24"
EW_START = 0x80
EW_RESULT = 0x8D
EW_DI_EVENT = 0x8E
EW_STOP = 0x90
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
    sample_time_us: float = 8.2
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
            sample_time_us=float(value.get("sample_time_us", 8.2)),
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


class EmWolfConnection:
    def __init__(
        self,
        on_log: Callable[[str], None],
        on_result: Callable[[int, bool, int], None],
        on_state: Callable[[bool], None],
        on_trip: Callable[[int, bool, int], None] | None = None,
    ) -> None:
        self._on_log = on_log
        self._on_result = on_result
        self._on_state = on_state
        self._on_trip = on_trip or (lambda _input_id, _value, _elapsed_us: None)
        self._socket: socket.socket | None = None
        self._ssh_process: subprocess.Popen[str] | None = None
        self._ssh_known_hosts = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
            / "WolfEye" / "ssh" / "emwolf_known_hosts"
        )
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._disconnect_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._di_debouncer = DIEventDebouncer()
        self._last_di_event: tuple[int, bool, int] | None = None

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
        try:
            ssh_process = self._start_remote_emwolf(host)
            self._on_log(f"Connecting to {host}:{port}...")
            connection = self._connect_after_ssh(host, port, ssh_process)
            connection.settimeout(0.5)
            with self._lock:
                self._socket = connection
            self._on_state(True)
            self._on_log("Connected")
            self._di_debouncer.reset()
            self._last_di_event = None

            decoder = FrameDecoder()
            while not self._stop.is_set():
                try:
                    received = connection.recv(4096)
                except TimeoutError:
                    continue
                if not received:
                    break
                for frame_type, payload in decoder.feed(received):
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
        except OSError as error:
            # A local Disconnect deliberately shuts the socket down while the
            # reader thread may still be inside recv(). Do not report that
            # expected wake-up as a connection failure.
            if not self._stop.is_set() and not self._disconnect_requested.is_set():
                self._on_log(f"Connection error: {error}")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            with self._lock:
                self._socket = None
            self._stop_remote_emwolf()
            self._on_state(False)
            self._on_log("Disconnected")

    def _start_remote_emwolf(self, host: str) -> subprocess.Popen[str]:
        self._ssh_known_hosts.parent.mkdir(parents=True, exist_ok=True)
        self._on_log(
            f"Starting EmWolf through SSH on {EMWOLF_SSH_USER}@{host}..."
        )
        process = subprocess.Popen(
            (
                "ssh",
                "-tt",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                f"UserKnownHostsFile={self._ssh_known_hosts.as_posix()}",
                "-o",
                f"GlobalKnownHostsFile={os.devnull}",
                f"{EMWOLF_SSH_USER}@{host}",
                EMWOLF_REMOTE_COMMAND,
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with self._lock:
            self._ssh_process = process
        return process

    def _connect_after_ssh(
        self, host: str, port: int, ssh_process: subprocess.Popen[str]
    ) -> socket.socket:
        deadline = time.monotonic() + EMWOLF_START_TIMEOUT_S
        last_error: OSError | None = None
        refreshed_host_key = False
        while not self._stop.is_set() and time.monotonic() < deadline:
            if ssh_process.poll() not in (None, 0):
                detail = self._read_ssh_error(ssh_process)
                if (
                    not refreshed_host_key
                    and "REMOTE HOST IDENTIFICATION HAS CHANGED" in detail
                ):
                    # The user authorized automatic key replacement for this lab board.
                    self._refresh_emwolf_host_key(host)
                    refreshed_host_key = True
                    if self._stop.is_set():
                        break
                    ssh_process = self._start_remote_emwolf(host)
                    deadline = time.monotonic() + EMWOLF_START_TIMEOUT_S
                    continue
                raise ConnectionError(
                    f"SSH could not start EmWolf{': ' + detail if detail else ''}"
                ) from last_error
            try:
                connection = socket.create_connection((host, port), timeout=1.0)
                if self._stop.is_set() or ssh_process.poll() not in (None, 0):
                    connection.close()
                    continue
                self._drain_ssh_errors(ssh_process)
                return connection
            except OSError as error:
                last_error = error
                self._stop.wait(0.2)
        if self._stop.is_set():
            raise ConnectionAbortedError("EmWolf connection was cancelled")
        raise TimeoutError(
            f"EmWolf did not open {host}:{port} within {EMWOLF_START_TIMEOUT_S:.0f} seconds"
        ) from last_error

    def _refresh_emwolf_host_key(self, host: str) -> None:
        """Replace only this host's entry in the app-owned SSH trust file."""
        if self._ssh_known_hosts.exists():
            try:
                result = subprocess.run(
                    ("ssh-keygen", "-R", host, "-f", str(self._ssh_known_hosts)),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as error:
                raise ConnectionError("Updating the EmWolf SSH host key timed out") from error
            if result.returncode:
                raise ConnectionError(f"Cannot update EmWolf SSH host key: {result.stderr.strip()}")
        self._on_log(
            f"EmWolf SSH key changed at {host}; replacing the saved key and reconnecting once."
        )

    def _drain_ssh_errors(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return

        def drain() -> None:
            for line in process.stderr:
                message = line.strip()
                if message:
                    self._on_log(f"SSH: {message}")

        threading.Thread(target=drain, daemon=True).start()

    @staticmethod
    def _read_ssh_error(process: subprocess.Popen[str]) -> str:
        if process.stderr is None:
            return ""
        return process.stderr.read().strip()

    def _stop_remote_emwolf(self) -> None:
        with self._lock:
            process, self._ssh_process = self._ssh_process, None
        if process is None or process.poll() is not None:
            return
        if process.stdin is not None:
            try:
                process.stdin.write("\x03")
                process.stdin.flush()
            except (OSError, ValueError):
                pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()

    def send_project(self, project: Project) -> None:
        payload = project.build_payload()
        frame = build_frame(EW_START, payload)
        with self._lock:
            connection = self._socket
        if connection is None:
            raise ConnectionError("Not connected to EmWolf")
        self._di_debouncer.reset()
        self._last_di_event = None
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
                connection.sendall(build_frame(EW_STOP, EW_STOP_TOKEN))
                self._on_log("Safe stop requested")
            except OSError as error:
                self._on_log(f"Could not send safe stop: {error}")
            self._stop.set()
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        else:
            self._stop.set()
        self._stop_remote_emwolf()
