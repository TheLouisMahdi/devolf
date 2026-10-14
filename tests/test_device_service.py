import struct
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from wolfeye.services.beacheye import PROVIDER_FIRMWARE, PROVIDER_TIMEOUT
from wolfeye.services.device_service import (
    CONNECTION_LEGACY,
    CONNECTION_NATIVE,
    FRAME_EVENTS,
    FRAME_GET_SETTINGS,
    FRAME_INFO,
    FRAME_MEASUREMENTS,
    FRAME_RESET,
    FRAME_SAVE_SETTINGS,
    DeviceService,
    LEGACY_CHECK_DOWNLOAD,
    LEGACY_FILE_EVENTS,
    LEGACY_FRAME_CHECK,
    LEGACY_FRAME_GET_SETTINGS,
    LEGACY_FRAME_STATUS,
    LEGACY_FRAME_DOWNLOAD,
    LEGACY_STATUS_FILE_SIZE,
    MAX_EVENTS_FILE_SIZE,
)


class _Provider:
    def __init__(self) -> None:
        self.requests: list[tuple[int, int, bytes]] = []
        self.updates: list[tuple[int, str, int, int]] = []
        self.starts: list[tuple[str, int, bool]] = []
        self.stopped = False
        self.fail_native = False
        self.fail_legacy = False

    def start(
        self,
        ip: str,
        port: int = 6536,
        timeout_ms: int = 5000,
        legacy_protocol: bool = False,
    ) -> None:
        del timeout_ms
        self.starts.append((ip, port, legacy_protocol))
        if (legacy_protocol and self.fail_legacy) or (
            not legacy_protocol and self.fail_native
        ):
            raise OSError("simulated connection failure")

    def request(self, tag: int, frame_type: int, payload: bytes = b"") -> None:
        self.requests.append((tag, frame_type, payload))

    def update_file(
        self, kind: int, path: str, hardware: int, bootloader: int
    ) -> None:
        self.updates.append((kind, path, hardware, bootloader))

    def stop(self) -> None:
        self.stopped = True


class DeviceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DeviceService()
        self.service._provider.close()
        self.provider = _Provider()
        self.service._provider = self.provider  # type: ignore[assignment]
        self.service.info.connected = True
        self.service.info.transport = "Native TCP:6536"

    def test_requests_delegate_to_native_provider_and_settings_follow_info(self) -> None:
        self.service._send_native_request("info", FRAME_INFO)
        self.service._send_native_request(
            "measurements", FRAME_MEASUREMENTS, b"\x03"
        )
        self.assertEqual(
            self.provider.requests[:2],
            [(1, FRAME_INFO, b""), (2, FRAME_MEASUREMENTS, b"\x03")],
        )

        info = bytes((1, 2, 3, 4)) + struct.pack("<HH", 50, 0) + b"commit00"
        self.service._handle_native_response("info", FRAME_INFO, info)
        self.assertEqual(self.provider.requests[2], (3, FRAME_GET_SETTINGS, b""))

    def test_settings_write_delegates_exact_payload(self) -> None:
        self.service.write_settings(b"native-settings")
        self.assertEqual(
            self.provider.requests[0],
            (4, FRAME_SAVE_SETTINGS, b"native-settings"),
        )

    def test_settings_write_finishes_on_company_success_response(self) -> None:
        self.service.write_settings(b"native-settings")

        self.service._handle_native_response("settings_write", 0x01, b"\x00")

        self.assertEqual(
            self.provider.requests,
            [(4, FRAME_SAVE_SETTINGS, b"native-settings")],
        )
        self.assertIsNone(self.service._pending_settings_write)

    def test_settings_write_rejects_error_status_without_follow_up_read(self) -> None:
        messages: list[tuple[str, str]] = []
        self.service.message.connect(lambda text, level: messages.append((text, level)))
        self.service.write_settings(b"native-settings")

        self.service._handle_native_response("settings_write", 0x01, b"\x06")

        self.assertEqual(len(self.provider.requests), 1)
        self.assertIsNone(self.service._pending_settings_write)
        self.assertTrue(any("status 0x06" in text for text, _level in messages))

    def test_event_request_selects_protocol_by_known_revision(self) -> None:
        self.service._legacy_protocol = False
        self.service.request_events()
        self.assertEqual(self.provider.requests[-1], (5, FRAME_EVENTS, b""))

        self.service._reset_event_download()
        self.service._legacy_protocol = True
        self.service.request_events()
        self.assertEqual(
            self.provider.requests[-1],
            (8, LEGACY_FRAME_CHECK, bytes((LEGACY_CHECK_DOWNLOAD, LEGACY_FILE_EVENTS))),
        )

    def test_native_events_retry_once_then_populate_ui_and_release_busy(self) -> None:
        changes, busy = [], []
        self.service.events_changed.connect(changes.append)
        self.service.busy_changed.connect(busy.append)
        self.service.request_events()
        self.service.request_events()
        self.assertEqual(len(self.provider.requests), 1)
        self.service._on_provider_event(PROVIDER_TIMEOUT, 5, 0, b"")
        self.assertEqual(len(self.provider.requests), 2)
        event = struct.pack("<H", 0x4000) + (12_600_000).to_bytes(6, "little")
        self.service._handle_native_response("events", 1, event)
        self.assertEqual(len(changes[0]), 1)
        self.assertEqual(busy, [True, False])
        self.assertFalse(self.service._event_active)

    def test_events_retry_limit_cancellation_and_fresh_request(self) -> None:
        busy = []
        self.service.busy_changed.connect(busy.append)
        self.service.request_events()
        for _ in range(3):
            self.service._on_provider_event(PROVIDER_TIMEOUT, 5, 0, b"")
        self.assertEqual(len(self.provider.requests), 3)
        self.assertFalse(self.service._event_active)
        self.assertEqual(busy, [True, False])
        self.service.request_events()
        self.service.disconnect_device()
        changes = []
        self.service.events_changed.connect(changes.append)
        self.service._handle_native_response("events", 1, bytes(8))
        self.assertEqual(changes, [])
        self.assertEqual(busy, [True, False, True, False])

    @patch.object(DeviceService, "_save_event_diagnostic", return_value="")
    def test_legacy_events_chunk_retries_preserve_snapshot_and_finish(self, _diagnostic) -> None:
        changes = []
        self.service.events_changed.connect(changes.append)
        self.service._legacy_protocol = True
        self.service.request_events()
        event = struct.pack("<H", 0x4000) + (12_600_000).to_bytes(6, "little")
        size = bytes((LEGACY_FRAME_CHECK, LEGACY_STATUS_FILE_SIZE)) + struct.pack("<I", len(event))
        self.service._handle_native_response("events_check", LEGACY_FRAME_STATUS, size)
        self.service._handle_native_response("events_chunk", LEGACY_FRAME_DOWNLOAD, bytes(2))
        self.assertEqual(self.service._event_sequence, 0)
        self.assertEqual(bytes(self.service._event_data), b"")
        self.service._handle_native_response("events_chunk", LEGACY_FRAME_DOWNLOAD, bytes(2) + event[:4])
        self.assertEqual(self.service._event_sequence, 1)
        self.service._handle_native_response("events_chunk", LEGACY_FRAME_DOWNLOAD, bytes(2) + event[:4])
        self.assertEqual(bytes(self.service._event_data), event[:4])
        self.service._on_provider_event(PROVIDER_TIMEOUT, 9, 0, b"")
        self.service._handle_native_response("events_chunk", LEGACY_FRAME_DOWNLOAD, b"\x01\x00" + event[4:])
        self.assertEqual(len(changes[0]), 1)
        self.assertFalse(self.service._event_active)

    def test_invalid_event_response_is_saved_exactly_and_has_bounded_retries(self) -> None:
        self.service.info.model = "FC22AR"
        self.service.info.build = 51
        payload = b"\xff" * 5512
        with tempfile.TemporaryDirectory() as temporary, patch.dict("os.environ", {"LOCALAPPDATA": temporary}):
            self.service.request_events()
            for _ in range(3):
                self.service._handle_native_response("events", 1, payload)
            capture = Path(temporary) / "DEVolf/diagnostics/events-response.bin"
            self.assertEqual(capture.read_bytes(), payload)
            metadata = json.loads(capture.with_suffix(".json").read_text())
            self.assertEqual((metadata["model"], metadata["build"], metadata["size"]), ("FC22AR", 51, 5512))
        self.assertEqual(len(self.provider.requests), 3)
        self.assertFalse(self.service._event_active)

    def test_legacy_event_size_limit_and_empty_file(self) -> None:
        self.service._legacy_protocol = True
        changes = []
        self.service.events_changed.connect(changes.append)
        with tempfile.TemporaryDirectory() as temporary, patch.dict("os.environ", {"LOCALAPPDATA": temporary}):
            self.service.request_events()
            too_large = bytes((LEGACY_FRAME_CHECK, LEGACY_STATUS_FILE_SIZE)) + struct.pack("<I", MAX_EVENTS_FILE_SIZE + 1)
            self.service._handle_native_response("events_check", LEGACY_FRAME_STATUS, too_large)
            self.assertEqual(bytes(self.service._event_data), b"")
            empty = bytes((LEGACY_FRAME_CHECK, LEGACY_STATUS_FILE_SIZE)) + bytes(4)
            self.service._handle_native_response("events_check", LEGACY_FRAME_STATUS, empty)
        self.assertEqual(changes, [[]])
        self.assertFalse(self.service._event_active)

    def test_reset_response_stops_native_provider(self) -> None:
        self.service.reset_device()
        self.assertEqual(self.provider.requests[0], (7, FRAME_RESET, b""))
        self.service._handle_native_response("reset", FRAME_RESET, b"\x00")
        self.assertTrue(self.provider.stopped)
        self.assertFalse(self.service.connected)

    def test_firmware_update_is_owned_by_native_provider(self) -> None:
        self.service.info.bootloader = 2
        self.service.info.hardware = 3
        self.service.update_file("Firmware", "firmware.bin")
        self.assertEqual(
            self.provider.updates,
            [(PROVIDER_FIRMWARE, "firmware.bin", 3, 2)],
        )

    def test_native_mode_uses_sequenced_tcp_and_requests_info(self) -> None:
        self.service.info.connected = False
        self.service._try_http_info = lambda _ip: None  # type: ignore[method-assign]

        self.service._connect_worker("192.168.137.10", CONNECTION_NATIVE)

        self.assertEqual(
            self.provider.starts,
            [("192.168.137.10", 6536, False)],
        )
        self.assertEqual(self.service.info.transport, "NATIVE TCP:6536")
        self.assertEqual(self.provider.requests[-1], (1, FRAME_INFO, b""))

    def test_native_handshake_does_not_depend_on_http(self) -> None:
        self.service.info.connected = False
        with patch.object(self.service, "_try_http_info", side_effect=AssertionError("HTTP must not run")):
            self.service._connect_worker("192.168.1.10", CONNECTION_NATIVE)
        self.assertEqual(self.provider.starts, [("192.168.1.10", 6536, False)])
        self.assertEqual(self.provider.requests, [(1, FRAME_INFO, b"")])

    def test_stop_during_legacy_http_probe_prevents_tcp_start(self) -> None:
        self.service.info.connected = False
        def canceled_probe(_ip):
            self.service._stop.set()
            return None
        with patch.object(self.service, "_try_http_info", side_effect=canceled_probe):
            self.service._connect_worker("192.168.1.10", CONNECTION_LEGACY)
        self.assertEqual(self.provider.starts, [])
        self.assertFalse(self.service.connected)

    def test_stop_during_tcp_start_prevents_late_connection(self) -> None:
        self.service.info.connected = False
        original_start = self.provider.start
        def canceled_start(*args, **kwargs):
            original_start(*args, **kwargs)
            self.service._stop.set()
        with patch.object(self.provider, "start", side_effect=canceled_start):
            self.service._connect_worker("192.168.1.10", CONNECTION_NATIVE)
        self.assertTrue(self.provider.stopped)
        self.assertFalse(self.service.connected)
        self.assertEqual(self.provider.requests, [])

    def test_legacy_text_identity_does_not_prevent_tcp_connection(self) -> None:
        self.service.info.connected = False
        with patch.object(self.service, "_try_http_info", return_value={
            "model": "FC22AR", "firmware": "V100", "hardware": "HW 2", "build": "V51"
        }):
            self.service._connect_worker("192.168.1.10", CONNECTION_LEGACY)
        self.assertEqual(self.provider.starts, [("192.168.1.10", 6536, True)])
        self.assertEqual((self.service.info.firmware, self.service.info.hardware), (100, 2))

    def test_legacy_mode_without_http_uses_unsequenced_tcp(self) -> None:
        self.service.info.connected = False
        self.service._try_http_info = lambda _ip: None  # type: ignore[method-assign]

        self.service._connect_worker("192.168.137.20", CONNECTION_LEGACY)

        self.assertEqual(
            self.provider.starts,
            [("192.168.137.20", 6536, True)],
        )
        self.assertEqual(self.service.info.build, 50)
        self.assertEqual(self.service.info.transport, "LEGACY TCP:6536")
        self.assertEqual(
            self.provider.requests[-1],
            (3, LEGACY_FRAME_GET_SETTINGS, b""),
        )

    def test_old_sectionalizer_legacy_mode_uses_verified_http(self) -> None:
        self.service.info.connected = False
        self.service._try_http_info = lambda _ip: {  # type: ignore[method-assign]
            "model": "FC22S",
            "firmware": 11,
            "hardware": 2,
            "build": 35,
        }
        poller_started: list[bool] = []
        self.service._start_legacy_http_poller = (  # type: ignore[method-assign]
            lambda: poller_started.append(True)
        )

        self.service._connect_worker("192.168.137.30", CONNECTION_LEGACY)

        self.assertEqual(self.provider.starts, [])
        self.assertEqual(self.service.info.transport, "LEGACY HTTP")
        self.assertEqual(self.service.info.model, "FC22S")
        self.assertEqual(poller_started, [True])

    def test_native_failure_automatically_tries_legacy_once(self) -> None:
        self.service.info.connected = False
        self.service._try_http_info = lambda _ip: None  # type: ignore[method-assign]
        self.provider.fail_native = True

        self.service._connect_worker("192.168.137.40", CONNECTION_NATIVE)

        self.assertEqual(
            self.provider.starts,
            [
                ("192.168.137.40", 6536, False),
                ("192.168.137.40", 6536, True),
            ],
        )
        self.assertEqual(self.service.info.transport, "LEGACY TCP:6536")

    def test_native_timeout_falls_back_only_once(self) -> None:
        self.service.info.connected = False
        self.service._try_http_info = lambda _ip: None  # type: ignore[method-assign]
        self.service._connection_ip = "192.168.137.50"

        self.service._connect_worker("192.168.137.50", CONNECTION_NATIVE)
        self.service._on_provider_event(PROVIDER_TIMEOUT, 1, 0, b"")
        fallback_worker = self.service._worker
        self.assertIsNotNone(fallback_worker)
        fallback_worker.join(timeout=2.0)

        self.service._on_provider_event(PROVIDER_TIMEOUT, 3, 0, b"")

        self.assertEqual(
            self.provider.starts,
            [
                ("192.168.137.50", 6536, False),
                ("192.168.137.50", 6536, True),
            ],
        )
        self.assertFalse(self.service.connected)


if __name__ == "__main__":
    unittest.main()
