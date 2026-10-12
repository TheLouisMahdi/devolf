import struct
import unittest

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

        self.service._legacy_protocol = True
        self.service.request_events()
        self.assertEqual(
            self.provider.requests[-1],
            (8, LEGACY_FRAME_CHECK, bytes((LEGACY_CHECK_DOWNLOAD, LEGACY_FILE_EVENTS))),
        )

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
