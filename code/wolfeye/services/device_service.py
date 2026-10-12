from __future__ import annotations

import ipaddress
import json
import struct
import threading
import urllib.error
import urllib.request

from wolfeye.qt import QObject, Signal

from wolfeye.models import (
    ANALOG_NAMES,
    BINARY_NAMES,
    COUNTER_NAMES,
    DeviceInfo,
    MeasurementSnapshot,
)
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
    decode_signal,
    normalize_device_model,
    normalize_device_revision,
)

WOLFEYE_PORT = 6536
CONNECTION_NATIVE = "NATIVE"
CONNECTION_LEGACY = "LEGACY"
LEGACY_SETTINGS_SIZE = 3744
FRAME_MEASUREMENTS = 0x02
FRAME_GET_SETTINGS = 0x03
FRAME_SAVE_SETTINGS = 0x04
FRAME_INFO = 0x05
FRAME_RESET = 0x06
FRAME_EVENTS = 0x07
FRAME_SIGNAL = 0x08
FRAME_FILE_FIRMWARE = 0x09
FRAME_FILE_BOOTLOADER = 0x0A
FRAME_CHECK_UPDATE_FIRMWARE = 0x0B
FRAME_CHECK_UPDATE_BOOTLOADER = 0x0C
FRAME_UPDATE_FIRMWARE_SIGNAL = 0x0D
FRAME_UPDATE_BOOTLOADER_SIGNAL = 0x0E
MEASUREMENT_BI_AI = 0x03
STATUS_RESETTING = 0x02
STATUS_OK = 0x00
STATUS_FILE_WRITE_SUCCESS = 0x05
STATUS_NO_NEED_UPLOAD = 0x09
LEGACY_FRAME_MEASUREMENTS = 0x01
LEGACY_FRAME_GET_SETTINGS = 0x02
LEGACY_FRAME_STATUS = 0x06
LEGACY_FRAME_SETTINGS = 0x07
LEGACY_FRAME_CHECK = 0x0E
LEGACY_FRAME_GET_SIGNAL = 0x0F
LEGACY_FRAME_RESET = 0x11
LEGACY_FRAME_DOWNLOAD = 0x13
LEGACY_STATUS_FILE_SIZE = 0x07
LEGACY_CHECK_DOWNLOAD = 0x02
LEGACY_FILE_EVENTS = 0x02

_COMMANDS = {
    "info": 1,
    "measurements": 2,
    "settings": 3,
    "settings_write": 4,
    "events": 5,
    "signal": 6,
    "reset": 7,
    "events_check": 8,
    "events_chunk": 9,
}
_COMMAND_NAMES = {value: name for name, value in _COMMANDS.items()}


class DeviceService(QObject):
    """Qt binding for the native C++ BeachEye DataProvider."""

    connection_changed = Signal(object)
    measurements_changed = Signal(object)
    events_changed = Signal(object)
    signal_received = Signal(object)
    settings_received = Signal(bytes)
    message = Signal(str, str)
    busy_changed = Signal(bool)
    update_progress = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.info = DeviceInfo()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._poller: threading.Thread | None = None
        self._request_lock = threading.Lock()
        self._connection_lock = threading.Lock()
        self._busy_lock = threading.Lock()
        self._busy_count = 0
        self._provider = NativeDataProvider(self._on_provider_event)
        self._connection_mode = CONNECTION_NATIVE
        self._legacy_protocol = False
        self._connection_ip = ""
        self._fallback_attempted = False
        self._handshake_complete = False
        self._startup_in_progress = False
        self._event_data = bytearray()
        self._event_size = 0
        self._event_sequence = 0
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
        self._stop.clear()
        with self._connection_lock:
            self._connection_ip = address
            self._connection_mode = CONNECTION_NATIVE
            self._fallback_attempted = False
            self._handshake_complete = False
            self._startup_in_progress = False
        self._worker = threading.Thread(
            target=self._connect_worker,
            args=(address, CONNECTION_NATIVE),
            daemon=True,
        )
        self._worker.start()

    def disconnect_device(self) -> None:
        self._stop.set()
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
        if self.info.transport == "LEGACY HTTP":
            if not self._request_lock.locked():
                threading.Thread(target=self._refresh_legacy_http, daemon=True).start()
        else:
            self._send_native_request(
                "measurements", FRAME_MEASUREMENTS, bytes((MEASUREMENT_BI_AI,))
            )

    def read_settings(self) -> None:
        if self.info.transport == "LEGACY HTTP":
            threading.Thread(target=self._read_legacy_http_settings, daemon=True).start()
        else:
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
        if self.info.transport == "LEGACY HTTP":
            self.message.emit(
                "LEGACY HTTP settings are read-only; use LEGACY TCP for device writes.",
                "warning",
            )
            return
        self._pending_settings_write = bytes(payload)
        self._send_native_request("settings_write", FRAME_SAVE_SETTINGS, payload)

    def request_events(self) -> None:
        if self.info.transport == "LEGACY HTTP":
            self._legacy_http_unsupported("event download")
            return
        if self._legacy_protocol:
            self._event_data.clear()
            self._event_size = 0
            self._event_sequence = 0
            self._send_native_request(
                "events_check",
                LEGACY_FRAME_CHECK,
                bytes((LEGACY_CHECK_DOWNLOAD, LEGACY_FILE_EVENTS)),
            )
        else:
            self._send_native_request("events", FRAME_EVENTS)

    def request_signal(self) -> None:
        if self.info.transport == "LEGACY HTTP":
            self._legacy_http_unsupported("signal download")
            return
        self._send_native_request("signal", FRAME_SIGNAL)

    def send_control(self, operation: str) -> None:
        self.message.emit(
            f"{operation} is display-only in the original WolfEye source; no device control frame was defined.",
            "info",
        )

    def reset_device(self) -> None:
        if self.info.transport == "LEGACY HTTP":
            self._legacy_http_unsupported("reset")
            return
        self._send_native_request("reset", FRAME_RESET)

    def update_file(self, kind: str, path: str) -> None:
        if not self.connected:
            self.message.emit("Connect to the WolfEye device first.", "warning")
            return
        if self.info.transport == "LEGACY HTTP":
            self._legacy_http_unsupported(f"{kind} transfer")
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

    def _connect_worker(self, ip: str, mode: str) -> None:
        self._set_busy(True)
        try:
            self._connect_attempt(ip, mode)
        except (OSError, ValueError, TypeError) as exc:
            if mode == CONNECTION_NATIVE and self._claim_legacy_fallback():
                self.message.emit(
                    f"NATIVE connection failed: {exc}. Trying LEGACY once...",
                    "warning",
                )
                try:
                    self._provider.stop()
                    self._connect_attempt(ip, CONNECTION_LEGACY)
                except (OSError, ValueError, TypeError) as legacy_exc:
                    self._set_connection_failed(
                        ip, f"LEGACY fallback failed: {legacy_exc}"
                    )
            else:
                self._set_connection_failed(ip, f"{mode} connection failed: {exc}")
        finally:
            self._set_busy(False)

    def _connect_attempt(self, ip: str, mode: str) -> None:
        if self._stop.is_set():
            raise OSError("connection was cancelled")
        with self._connection_lock:
            self._connection_ip = ip
            self._connection_mode = mode
            self._handshake_complete = False
        self.message.emit(f"Connecting to {ip} using {mode}...", "info")

        http_info = self._try_http_info(ip)
        build = (
            normalize_device_revision(
                http_info.get("build", http_info.get("revision", 0))
            )
            if http_info
            else 0
        )
        model = (
            normalize_device_model(http_info.get("model", "WolfEye"))
            if http_info
            else "WolfEye"
        )
        firmware = int(http_info.get("firmware", 0)) if http_info else 0
        hardware = int(http_info.get("hardware", 0)) if http_info else 0

        if mode == CONNECTION_LEGACY and self._uses_legacy_http(http_info, build):
            self._connect_legacy_http(ip, model, firmware, hardware, build)
            return

        self._legacy_protocol = mode == CONNECTION_LEGACY
        with self._connection_lock:
            self._startup_in_progress = True
        try:
            self._provider.start(
                ip, WOLFEYE_PORT, legacy_protocol=self._legacy_protocol
            )
        finally:
            with self._connection_lock:
                self._startup_in_progress = False
        self.info = DeviceInfo(
            ip=ip,
            model=model,
            firmware=firmware,
            hardware=hardware,
            build=build or (50 if self._legacy_protocol else 0),
            connected=True,
            transport=(
                f"LEGACY TCP:{WOLFEYE_PORT}"
                if self._legacy_protocol
                else f"NATIVE TCP:{WOLFEYE_PORT}"
            ),
        )
        self.connection_changed.emit(self.info)
        self.message.emit(
            f"Connected to {ip}:{WOLFEYE_PORT} using {mode}", "success"
        )
        if self._legacy_protocol:
            self._send_native_request("settings", LEGACY_FRAME_GET_SETTINGS)
        else:
            self._send_native_request("info", FRAME_INFO)

    def _claim_legacy_fallback(self) -> bool:
        with self._connection_lock:
            if (
                self._stop.is_set()
                or self._connection_mode != CONNECTION_NATIVE
                or self._fallback_attempted
                or self._handshake_complete
            ):
                return False
            self._fallback_attempted = True
            return True

    def _queue_legacy_fallback(self, reason: str) -> bool:
        if not self._claim_legacy_fallback():
            return False
        with self._connection_lock:
            ip = self._connection_ip
        if not ip:
            return False
        self.message.emit(
            f"NATIVE connection failed: {reason}. Trying LEGACY once...",
            "warning",
        )
        self._worker = threading.Thread(
            target=self._legacy_fallback_worker, args=(ip,), daemon=True
        )
        self._worker.start()
        return True

    def _legacy_fallback_worker(self, ip: str) -> None:
        self._set_busy(True)
        try:
            self._provider.stop()
            self._connect_attempt(ip, CONNECTION_LEGACY)
        except (OSError, ValueError, TypeError) as exc:
            self._set_connection_failed(ip, f"LEGACY fallback failed: {exc}")
        finally:
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        with self._busy_lock:
            was_busy = self._busy_count > 0
            self._busy_count = max(0, self._busy_count + (1 if busy else -1))
            is_busy = self._busy_count > 0
        if is_busy != was_busy:
            self.busy_changed.emit(is_busy)

    def _set_connection_failed(self, ip: str, text: str) -> None:
        self.info = DeviceInfo(ip=ip, connected=False, transport="Offline")
        self.connection_changed.emit(self.info)
        self.message.emit(text, "error")

    def _fail_legacy_handshake(self, reason: str, *, stop_provider: bool) -> bool:
        with self._connection_lock:
            if (
                self._connection_mode != CONNECTION_LEGACY
                or self._handshake_complete
                or not self._connection_ip
            ):
                return False
            ip = self._connection_ip
            self._connection_ip = ""
        self._set_connection_failed(ip, f"LEGACY fallback failed: {reason}")
        if stop_provider:
            threading.Thread(target=self._provider.stop, daemon=True).start()
        return True

    def _initial_connection_pending(self) -> bool:
        with self._connection_lock:
            return not self._handshake_complete and bool(self._connection_ip)

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
            if self._legacy_protocol:
                frame_type = {
                    "measurements": LEGACY_FRAME_MEASUREMENTS,
                    "settings": LEGACY_FRAME_GET_SETTINGS,
                    "settings_write": LEGACY_FRAME_SETTINGS,
                    "signal": LEGACY_FRAME_GET_SIGNAL,
                    "reset": LEGACY_FRAME_RESET,
                }.get(command, frame_type)
            self._provider.request(_COMMANDS[command], frame_type, command_payload)
        except (KeyError, OSError) as exc:
            if command == "settings_write":
                self._pending_settings_write = None
            self.message.emit(f"Native {command} request failed: {exc}", "error")

    def _on_provider_event(
        self, event: int, tag: int, value: int, payload: bytes
    ) -> None:
        if event == PROVIDER_RESPONSE:
            command = _COMMAND_NAMES.get(tag)
            if command:
                self._handle_native_response(command, value, payload)
            return
        if event == PROVIDER_TIMEOUT:
            command = _COMMAND_NAMES.get(tag, f"command {tag}")
            if command == "settings_write":
                self._pending_settings_write = None
            if (
                self._connection_mode == CONNECTION_NATIVE
                and command == "info"
                and self._initial_connection_pending()
                and self._queue_legacy_fallback("device info request timed out")
            ):
                return
            if (
                command == "settings"
                and self._fail_legacy_handshake(
                    "settings request timed out", stop_provider=True
                )
            ):
                return
            self.message.emit(f"WolfEye {command} request timed out.", "error")
            return
        if event == PROVIDER_ERROR:
            text = payload.decode("utf-8", errors="replace") or "Native provider error"
            command = _COMMAND_NAMES.get(tag)
            if command == "settings_write":
                self._pending_settings_write = None
            with self._connection_lock:
                startup_in_progress = self._startup_in_progress
            if startup_in_progress:
                return
            if (
                self._connection_mode == CONNECTION_NATIVE
                and self._initial_connection_pending()
                and self._queue_legacy_fallback(text)
            ):
                return
            if self._fail_legacy_handshake(text, stop_provider=True):
                return
            self.message.emit(text, "error")
            return
        if event == PROVIDER_DISCONNECTED:
            self._pending_settings_write = None
            mode = self._connection_mode
            if (
                mode == CONNECTION_NATIVE
                and self._initial_connection_pending()
                and self._queue_legacy_fallback("connection closed during handshake")
            ):
                return
            if self._fail_legacy_handshake(
                "connection closed during handshake", stop_provider=False
            ):
                return
            self.info.connected = False
            self.info.transport = "Offline"
            self.connection_changed.emit(self.info)
            self.message.emit(f"{mode} connection closed.", "warning")
            return
        if event == PROVIDER_UPDATE_PROGRESS:
            self.update_progress.emit(value, self._update_kind(tag))
            return
        if event == PROVIDER_UPDATE_FINISHED:
            text = payload.decode("utf-8", errors="replace")
            self.message.emit(text, "success" if value else "error")
            if value:
                self.disconnect_device()

    def _handle_native_response(
        self, command: str, _frame_type: int, payload: bytes
    ) -> None:
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
                if self._connection_mode == CONNECTION_LEGACY:
                    self._mark_handshake_complete()
                self.settings_received.emit(payload)
                self.message.emit(
                    f"Read {len(payload):,} WolfEye setting bytes.", "success"
                )
            elif command == "settings_write":
                if not payload:
                    raise ValueError("device returned an empty settings status")
                status = payload[1] if self._legacy_protocol and len(payload) > 1 else payload[0]
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
            elif command == "events":
                records = decode_events(payload, self.info.model, self.info.build)
                self.events_changed.emit(records)
                self.message.emit(
                    f"Loaded {len(records)} WolfEye event(s).", "success"
                )
            elif command == "signal":
                self.signal_received.emit(decode_signal(payload))
                self.message.emit("WolfEye signal loaded.", "success")
            elif command == "reset":
                self.message.emit(
                    "RESET accepted; reconnect after the device restarts.", "success"
                )
                self.disconnect_device()
            elif command == "events_check":
                if (
                    _frame_type != LEGACY_FRAME_STATUS
                    or len(payload) < 6
                    or payload[0] != LEGACY_FRAME_CHECK
                    or payload[1] != LEGACY_STATUS_FILE_SIZE
                ):
                    raise ValueError("device did not return the legacy events file size")
                self._event_size = struct.unpack_from("<I", payload, 2)[0]
                if not self._event_size:
                    self.events_changed.emit([])
                    self.message.emit("No WolfEye events are available.", "info")
                else:
                    self._request_next_event_chunk()
            elif command == "events_chunk":
                if len(payload) < 2:
                    raise ValueError("device returned an incomplete events chunk")
                sequence = struct.unpack_from("<H", payload)[0]
                if sequence != self._event_sequence:
                    raise ValueError(
                        f"unexpected events chunk {sequence}; expected {self._event_sequence}"
                    )
                self._event_data.extend(payload[2:])
                self._event_sequence += 1
                if len(self._event_data) < self._event_size:
                    self._request_next_event_chunk()
                else:
                    data = bytes(self._event_data[: self._event_size])
                    records = decode_events(data, self.info.model, self.info.build)
                    self.events_changed.emit(records)
                    self.message.emit(
                        f"Loaded {len(records)} WolfEye event(s).", "success"
                    )
        except (ValueError, struct.error) as exc:
            if (
                command == "info"
                and self._connection_mode == CONNECTION_NATIVE
                and self._queue_legacy_fallback(f"invalid device info response: {exc}")
            ):
                return
            self.message.emit(f"WolfEye {command} decode failed: {exc}", "error")

    @staticmethod
    def _update_kind(kind: int) -> str:
        return "Firmware" if kind == PROVIDER_FIRMWARE else "Bootloader"

    def _request_next_event_chunk(self) -> None:
        self._send_native_request(
            "events_chunk",
            LEGACY_FRAME_DOWNLOAD,
            struct.pack("<H", self._event_sequence),
        )

    @staticmethod
    def _uses_legacy_http(
        http_info: dict[str, object] | None, build: int
    ) -> bool:
        if not http_info:
            return False
        model = str(http_info.get("model", ""))
        return build <= 0 or (model[4:5].upper() == "S" and build < 40)

    def _connect_legacy_http(
        self,
        ip: str,
        model: str,
        firmware: int,
        hardware: int,
        build: int,
    ) -> None:
        self._legacy_protocol = False
        self._mark_handshake_complete()
        self.info = DeviceInfo(
            ip=ip,
            model=model,
            firmware=firmware,
            hardware=hardware,
            build=build,
            connected=True,
            transport="LEGACY HTTP",
        )
        self.connection_changed.emit(self.info)
        self.message.emit(f"Connected to {ip} using LEGACY HTTP", "success")
        self._start_legacy_http_poller()

    def _start_legacy_http_poller(self) -> None:
        if self._poller and self._poller.is_alive():
            return

        def loop() -> None:
            while (
                not self._stop.wait(1.0)
                and self.connected
                and self.info.transport == "LEGACY HTTP"
            ):
                self._refresh_legacy_http()

        self._poller = threading.Thread(target=loop, daemon=True)
        self._poller.start()

    def _refresh_legacy_http(self) -> None:
        if not self._request_lock.acquire(blocking=False):
            return
        try:
            body = self._http_get(self.info.ip, "/measurements", timeout=3.0)
            analog_raw = self._between(body, b'{"analogs":"', b'","binaries":"')
            binary_raw = self._between(body, b'","binaries":"', b'","counters":"')
            counter_raw = self._between(body, b'","counters":"', b'"}')
            analog_size = len(ANALOG_NAMES) * 2
            binary_size = len(BINARY_NAMES)
            counter_size = len(COUNTER_NAMES) * 4
            if (
                len(analog_raw) < analog_size
                or len(binary_raw) < binary_size
                or len(counter_raw) < counter_size
            ):
                raise ValueError(
                    "Measurement response is shorter than the supplied point definitions"
                )
            analog_values = struct.unpack(
                f"<{len(ANALOG_NAMES)}H", analog_raw[:analog_size]
            )
            counter_values = struct.unpack(
                f"<{len(COUNTER_NAMES)}I", counter_raw[:counter_size]
            )
            self.measurements_changed.emit(
                MeasurementSnapshot(
                    analog={
                        name: float(value)
                        for name, value in zip(ANALOG_NAMES, analog_values)
                    },
                    binary={
                        name: bool(value)
                        for name, value in zip(BINARY_NAMES, binary_raw[:binary_size])
                    },
                    counters={
                        name: int(value)
                        for name, value in zip(COUNTER_NAMES, counter_values)
                    },
                )
            )
        except (OSError, ValueError, struct.error) as exc:
            self.message.emit(f"LEGACY HTTP measurement failed: {exc}", "error")
        finally:
            self._request_lock.release()

    def _read_legacy_http_settings(self) -> None:
        try:
            body = self._http_get(self.info.ip, "/settings", timeout=5.0)
            marker = b'{"data":"'
            start = body.find(marker)
            if start < 0:
                raise ValueError("Missing legacy settings payload")
            start += len(marker)
            payload = body[start : start + LEGACY_SETTINGS_SIZE]
            if len(payload) != LEGACY_SETTINGS_SIZE:
                raise ValueError(
                    f"Legacy settings payload is shorter than {LEGACY_SETTINGS_SIZE} bytes"
                )
            self.settings_received.emit(payload)
            self.message.emit(
                f"Read {len(payload):,} LEGACY HTTP setting bytes.", "success"
            )
        except (OSError, ValueError) as exc:
            self.message.emit(f"LEGACY HTTP settings read failed: {exc}", "error")

    def _legacy_http_unsupported(self, operation: str) -> None:
        self.message.emit(
            f"LEGACY HTTP does not define {operation}; select LEGACY TCP when the device supports port {WOLFEYE_PORT}.",
            "warning",
        )

    @staticmethod
    def _between(body: bytes, start_token: bytes, end_token: bytes) -> bytes:
        start = body.find(start_token)
        if start < 0:
            raise ValueError(f"Missing response field: {start_token!r}")
        start += len(start_token)
        end = body.find(end_token, start)
        if end < 0:
            raise ValueError("Malformed device response")
        return body[start:end]

    @staticmethod
    def _http_get(ip: str, path: str, timeout: float) -> bytes:
        try:
            request = urllib.request.Request(
                f"http://{ip}{path}", headers={"Connection": "close"}
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.URLError as exc:
            raise OSError(getattr(exc, "reason", exc)) from exc

    @staticmethod
    def _try_http_info(ip: str) -> dict[str, object] | None:
        try:
            value = json.loads(
                DeviceService._http_get(ip, "/info", timeout=3.0).decode(
                    "utf-8", errors="strict"
                )
            )
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError, urllib.error.URLError):
            return None
