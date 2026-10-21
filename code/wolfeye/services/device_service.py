from __future__ import annotations

import ipaddress
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from wolfeye.qt import QObject, Signal

from wolfeye.models import DeviceInfo
from wolfeye.services.beacheye import (
    PROVIDER_BOOTLOADER,
    PROVIDER_DISCONNECTED,
    PROVIDER_ERROR,
    PROVIDER_FIRMWARE,
    PROVIDER_RESPONSE,
    PROVIDER_TIMEOUT,
    PROVIDER_UPDATE_FINISHED,
    PROVIDER_UPDATE_PROGRESS,
    NativeDataProvider,
    decode_events,
    decode_info,
    decode_measurements,
    normalize_device_model,
    normalize_device_revision,
)

from wolfeye.services.wolfeye import decode_signal, decode_adc

WOLFEYE_PORT = 6536
FRAME_MEASUREMENTS = 0x02
FRAME_GET_SETTINGS = 0x03
FRAME_SAVE_SETTINGS = 0x04
FRAME_INFO = 0x05
FRAME_RESET = 0x06
FRAME_EVENTS = 0x07
FRAME_SIGNAL = 0x08
FRAME_ADC = 0x11
MEASUREMENT_BI_AI = 0x03
STATUS_OK = 0x00
STATUS_NO_NEED_UPLOAD = 0x09
EVENT_RETRIES = 2
EVENT_COMMANDS = frozenset(("events",))

_COMMANDS = {
    "info": 1,
    "measurements": 2,
    "settings": 3,
    "settings_write": 4,
    "events": 5,
    "signal": 6,
    "reset": 7,
    "adc": 8,
}
_COMMAND_NAMES = {value: name for name, value in _COMMANDS.items()}


class DeviceService(QObject):
    """Qt binding for the native C++ BeachEye DataProvider."""

    connection_changed = Signal(object)
    measurements_changed = Signal(object)
    events_changed = Signal(object)
    signal_received = Signal(object)
    adc_received = Signal(object)
    settings_received = Signal(bytes)
    message = Signal(str, str)
    busy_changed = Signal(bool)
    update_progress = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.info = DeviceInfo()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._connection_lock = threading.Lock()
        self._busy_lock = threading.Lock()
        self._busy_count = 0
        self._provider = NativeDataProvider(self._on_provider_event)
        self._connection_ip = ""
        self._handshake_complete = False
        self._startup_in_progress = False
        self._event_lock = threading.RLock()
        self._event_active = False
        self._event_phase = ""
        self._event_retries = 0
        self._pending_settings_write: bytes | None = None

    @property
    def connected(self) -> bool:
        return self.info.connected

    def connect_device(self, ip: str) -> None:
        if self._worker and self._worker.is_alive():
            return
        try:
            address = str(ipaddress.ip_address(ip.strip()))
        except ValueError:
            self.message.emit("IP address is invalid.", "error")
            return
        self._reset_event_download()
        self._stop.clear()
        with self._connection_lock:
            self._connection_ip = address
            self._handshake_complete = False
            self._startup_in_progress = False
        self._worker = threading.Thread(
            target=self._connect_worker,
            args=(address,),
            daemon=True,
        )
        self._worker.start()

    def disconnect_device(self) -> None:
        self._stop.set()
        self._reset_event_download()
        self._pending_settings_write = None
        with self._connection_lock:
            self._connection_ip = ""
            self._handshake_complete = False
        was_connected = self.info.connected
        self._provider.stop()
        self.info.connected = False
        self.info.transport = "Offline"
        self.connection_changed.emit(self.info)
        if was_connected:
            self.message.emit("Disconnected", "info")

    def refresh(self) -> None:
        self._send_native_request("measurements", FRAME_MEASUREMENTS, bytes((MEASUREMENT_BI_AI,)))

    def read_settings(self) -> None:
        self._send_native_request("settings", FRAME_GET_SETTINGS)

    def write_settings(self, payload: bytes) -> None:
        if not payload:
            self.message.emit(
                "Read or open a valid WolfEye settings payload before writing.",
                "warning",
            )
            return
        if not self.connected:
            self.message.emit("Connect to the WolfEye device first.", "warning")
            return
        self._pending_settings_write = bytes(payload)
        self._send_native_request("settings_write", FRAME_SAVE_SETTINGS, payload)

    def request_events(self) -> None:
        if not self.connected:
            self.message.emit("Connect to the WolfEye device first.", "warning")
            return
        with self._event_lock:
            if self._event_active:
                self.message.emit("Events are already being downloaded.", "info")
                return
            self._event_active = True
            self._event_retries = 0
            self._event_phase = "events"
            self._set_busy(True)
            self._request_event_phase()

    def _request_event_phase(self) -> None:
        self._send_native_request("events", FRAME_EVENTS)

    def request_signal(self) -> None:
        self._send_native_request("signal", FRAME_SIGNAL)

    def request_adc(self) -> None:
        self._send_native_request("adc", FRAME_ADC)

    def send_control(self, operation: str) -> None:
        self.message.emit(
            f"{operation} is display-only in the original WolfEye source; no device control frame was defined.",
            "info",
        )

    def reset_device(self) -> None:
        self._send_native_request("reset", FRAME_RESET)

    def update_file(self, kind: str, path: str) -> None:
        if not self.connected:
            self.message.emit("Connect to the WolfEye device first.", "warning")
            return
        update_kind = (
            PROVIDER_FIRMWARE
            if kind.casefold() == "firmware"
            else PROVIDER_BOOTLOADER
        )
        try:
            self._provider.update_file(
                update_kind, path, self.info.hardware, self.info.bootloader
            )
        except (OSError, ValueError):
            # The native provider already reports the precise validation error.
            pass

    def _connect_worker(self, ip: str) -> None:
        self._set_busy(True)
        try:
            self._connect_attempt(ip)
        except (OSError, ValueError, TypeError) as exc:
            self._set_connection_failed(ip, f"BeachEye connection failed: {exc}")
        finally:
            self._set_busy(False)

    def _connect_attempt(self, ip: str) -> None:
        if self._stop.is_set():
            raise OSError("connection was cancelled")
        with self._connection_lock:
            self._connection_ip = ip
            self._handshake_complete = False
            self._startup_in_progress = True
        self.message.emit(f"Connecting to {ip} using BeachEye...", "info")
        try:
            self._provider.start(ip, WOLFEYE_PORT)
        finally:
            with self._connection_lock:
                self._startup_in_progress = False
        if self._stop.is_set():
            self._provider.stop()
            raise OSError("connection was cancelled")
        self.info = DeviceInfo(ip=ip, connected=True, transport=f"BeachEye TCP:{WOLFEYE_PORT}")
        self.connection_changed.emit(self.info)
        self._send_native_request("info", FRAME_INFO)

    def _set_busy(self, busy: bool) -> None:
        with self._busy_lock:
            was_busy = self._busy_count > 0
            self._busy_count = max(0, self._busy_count + (1 if busy else -1))
            is_busy = self._busy_count > 0
        if is_busy != was_busy:
            self.busy_changed.emit(is_busy)

    def _set_connection_failed(self, ip: str, text: str) -> None:
        with self._connection_lock:
            self._connection_ip = ""
            self._handshake_complete = False
        self._pending_settings_write = None
        self._reset_event_download()
        self.info = DeviceInfo(ip=ip, connected=False, transport="Offline")
        self.connection_changed.emit(self.info)
        self.message.emit(text, "error")

    def _fail_handshake(self, reason: str) -> bool:
        with self._connection_lock:
            if self._handshake_complete or not self._connection_ip:
                return False
            ip = self._connection_ip
            self._connection_ip = ""
        self._set_connection_failed(ip, f"BeachEye handshake failed: {reason}")
        self._provider.stop()
        return True

    def _mark_handshake_complete(self) -> None:
        with self._connection_lock:
            self._handshake_complete = True

    def _send_native_request(
        self, command: str, frame_type: int, command_payload: bytes = b""
    ) -> None:
        if not self.connected:
            self.message.emit("Connect to the WolfEye device first.", "warning")
            return
        try:
            self._provider.request(_COMMANDS[command], frame_type, command_payload)
        except (KeyError, OSError) as exc:
            if command == "settings_write":
                self._pending_settings_write = None
            if command in EVENT_COMMANDS:
                self._reset_event_download()
            self.message.emit(f"Native {command} request failed: {exc}", "error")

    def _on_provider_event(self, event: int, tag: int, value: int, payload: bytes) -> None:
        if event == PROVIDER_RESPONSE:
            command = _COMMAND_NAMES.get(tag)
            if command:
                self._handle_native_response(command, value, payload)
        elif event == PROVIDER_TIMEOUT:
            command = _COMMAND_NAMES.get(tag, f"command {tag}")
            if command in EVENT_COMMANDS:
                self._retry_event_download(command, "request timed out")
                return
            if command == "settings_write":
                self._pending_settings_write = None
            if command == "info" and self._fail_handshake("device info request timed out"):
                return
            self.message.emit(f"BeachEye {command} request timed out.", "error")
        elif event == PROVIDER_ERROR:
            text = payload.decode("utf-8", errors="replace") or "BeachEye provider error"
            command = _COMMAND_NAMES.get(tag)
            if command in EVENT_COMMANDS:
                self._retry_event_download(command, text)
                return
            if command == "settings_write":
                self._pending_settings_write = None
            with self._connection_lock:
                startup_in_progress = self._startup_in_progress
            if startup_in_progress or self._fail_handshake(text):
                return
            self.message.emit(text, "error")
        elif event == PROVIDER_DISCONNECTED:
            self._reset_event_download()
            self._pending_settings_write = None
            with self._connection_lock:
                self._connection_ip = ""
            self.info.connected = False
            self.info.transport = "Offline"
            self.connection_changed.emit(self.info)
            self.message.emit("BeachEye connection closed.", "warning")
        elif event == PROVIDER_UPDATE_PROGRESS:
            self.update_progress.emit(value, self._update_kind(tag))
        elif event == PROVIDER_UPDATE_FINISHED:
            text = payload.decode("utf-8", errors="replace")
            self.message.emit(text, "success" if value else "error")
            if value:
                self.disconnect_device()

    def _handle_native_response(
        self, command: str, _frame_type: int, payload: bytes
    ) -> None:
        if command in EVENT_COMMANDS:
            self._handle_event_response(command, _frame_type, payload)
            return
        diagnostic = ""
        try:
            if command == "info":
                info = decode_info(payload)
                self._mark_handshake_complete()
                self.info.model = normalize_device_model(info["model"])
                self.info.firmware = int(info["firmware"])
                self.info.hardware = int(info["hardware"])
                self.info.bootloader = int(info["bootloader"])
                self.info.build = normalize_device_revision(info["build"])
                self.info.flags = int(info["flags"])
                self.info.commit = str(info["commit"])
                self.connection_changed.emit(self.info)
                self.message.emit(
                    f"WolfEye device info loaded: {self.info.model}, build {self.info.build}",
                    "success",
                )
                # Matches DataProvider::InfoDeserialize in the company source.
                self._send_native_request("settings", FRAME_GET_SETTINGS)
            elif command == "measurements":
                snapshot = decode_measurements(
                    payload, self.info.model, self.info.build
                )
                self.measurements_changed.emit(snapshot)
                self.message.emit("WolfEye measurements loaded.", "success")
            elif command == "settings":
                self.settings_received.emit(payload)
                self.message.emit(
                    f"Read {len(payload):,} WolfEye setting bytes.", "success"
                )
            elif command == "settings_write":
                if not payload:
                    raise ValueError("device returned an empty settings status")
                status = payload[0]
                if status not in (STATUS_OK, STATUS_NO_NEED_UPLOAD):
                    self._pending_settings_write = None
                    raise ValueError(f"device rejected settings with status 0x{status:02X}")
                self._pending_settings_write = None
                self.message.emit(
                    "Same settings; no write was needed."
                    if status == STATUS_NO_NEED_UPLOAD
                    else "New WolfEye settings applied.",
                    "info" if status == STATUS_NO_NEED_UPLOAD else "success",
                )
            elif command == "signal":
                diagnostic = self._save_signal_diagnostic(payload)
                self.signal_received.emit(decode_signal(payload, self.info.signal_samples))
                self.message.emit(f"WolfEye signal loaded.{diagnostic}", "success")
            elif command == "adc":
                diagnostic = self._save_signal_diagnostic(payload, "adc")
                self.adc_received.emit(decode_adc(payload, self.info.signal_samples))
                self.message.emit(f"WolfEye raw ADC loaded.{diagnostic}", "success")
            elif command == "reset":
                self.message.emit(
                    "RESET accepted; reconnect after the device restarts.", "success"
                )
                self.disconnect_device()
        except ValueError as exc:
            if command == "info" and self._fail_handshake(f"invalid device info response: {exc}"):
                return
            self.message.emit(f"WolfEye {command} decode failed: {exc}{diagnostic}", "error")

    @staticmethod
    def _update_kind(kind: int) -> str:
        return "Firmware" if kind == PROVIDER_FIRMWARE else "Bootloader"

    def _reset_event_download(self) -> None:
        with self._event_lock:
            active = self._event_active
            self._event_active = False
            self._event_phase = ""
            self._event_retries = 0
            if active:
                self._set_busy(False)

    def _retry_event_download(self, command: str, reason: str) -> None:
        with self._event_lock:
            if not self._event_active or command != self._event_phase:
                return
            if self._event_retries >= EVENT_RETRIES:
                self._reset_event_download()
                self.message.emit(f"Event download failed after retries: {reason}", "error")
                return
            self._event_retries += 1
            self.message.emit(
                f"Retrying events ({self._event_retries}/{EVENT_RETRIES}): {reason}",
                "warning",
            )
            self._request_event_phase()

    def _handle_event_response(self, command: str, frame_type: int, payload: bytes) -> None:
        with self._event_lock:
            if not self._event_active or command != self._event_phase:
                return
            try:
                records = decode_events(payload, self.info.model, self.info.build)
                self._reset_event_download()
                self.events_changed.emit(records)
                self.message.emit(
                    f"Loaded {len(records)} BeachEye event(s)." if records
                    else "No BeachEye events are available.", "success" if records else "info",
                )
            except ValueError as exc:
                diagnostic = self._save_event_diagnostic(command, frame_type, payload, str(exc))
                self._retry_event_download(command, f"{self.info.model} build {self.info.build}: {exc}{diagnostic}")

    def _save_signal_diagnostic(self, payload: bytes, command: str = "signal") -> str:
        """Keep exact user-requested SIGNAL/ADC bodies for firmware comparison."""
        try:
            directory = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "DEVolf" / "diagnostics"
            directory.mkdir(parents=True, exist_ok=True)
            capture = directory / f"{command}-response.bin"
            capture.write_bytes(payload)
            capture.with_suffix(".json").write_text(json.dumps({
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "model": self.info.model, "build": self.info.build,
                "firmware": self.info.firmware, "hardware": self.info.hardware,
                "command": command, "frame_type": FRAME_ADC if command == "adc" else FRAME_SIGNAL,
                "payload_bytes": len(payload),
                "info_flags": self.info.flags,
                "sample_count_expected": self.info.signal_samples,
                "sample_rate_hz_expected": self.info.signal_samples * 50,
                "channel_order": ["Ia", "Ib", "Ic", "In", "Va", "Vb", "Vc", "Vr", "Vs", "Vt"],
                "data_type": "little-endian uint16, half-cycle voltage/current blocks" if command == "adc"
                             else "little-endian float32, channel-major; only the INFO-selected prefix is plotted",
            }, indent=2), encoding="utf-8")
            return f" Raw response saved to {capture}"
        except OSError as exc:
            return f" Diagnostic save failed: {exc}"

    def _save_event_diagnostic(self, command: str, frame_type: int, data: bytes, error: str) -> str:
        try:
            directory = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "DEVolf" / "diagnostics"
            directory.mkdir(parents=True, exist_ok=True)
            capture = directory / "events-response.bin"
            capture.write_bytes(data)
            capture.with_suffix(".json").write_text(json.dumps({
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "model": self.info.model, "build": self.info.build,
                "firmware": self.info.firmware, "hardware": self.info.hardware,
                "bootloader": self.info.bootloader, "bridge_abi": 10,
                "transport": self.info.transport, "command": command,
                "frame_type": frame_type, "size": len(data), "error": error,
            }, indent=2), encoding="utf-8")
            return f"; raw response saved to {capture}"
        except OSError as exc:
            return f"; diagnostic save failed: {exc}"
