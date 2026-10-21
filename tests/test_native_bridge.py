import unittest
from binascii import crc_hqx
import struct
import socket
import tempfile
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from wolfeye.services import beacheye

from wolfeye.services.beacheye import (
    PROVIDER_FIRMWARE,
    PROVIDER_RESPONSE,
    PROVIDER_UPDATE_FINISHED,
    NativeDataProvider,
    build_native_frame,
    decode_native_frame,
    decode_info,
    decode_measurements,
    decode_events,
    decode_settings_payload,
    decode_settings_file,
    default_settings_json,
    default_settings_file,
    encode_settings_file,
    normalize_device_model,
    normalize_device_revision,
    patch_settings_payload,
    settings_point_catalog,
)
from wolfeye.config_schema import default_config
from wolfeye.services.native_config import (
    update_config_from_native,
    update_native_from_config,
)


class NativeBridgeTests(unittest.TestCase):
    def test_old_event_bridge_abi_requires_rebuild_before_calling_changed_api(self) -> None:
        beacheye._native.cache_clear()
        try:
            for version in (6, 7, 8, 9, 10, 11):
                with patch.object(beacheye.ct, "CDLL") as loader:
                    loader.return_value.be_abi_version.return_value = version
                    with self.assertRaisesRegex(ValueError, "rebuild"):
                        beacheye._native()
                    loader.return_value.be_events_named.assert_not_called()
        finally:
            beacheye._native.cache_clear()

    def test_device_revision_never_selects_a_different_company_dll(self) -> None:
        beacheye._native.cache_clear()
        try:
            # Even a stale packaged revision DLL must not determine the source.
            with patch.object(Path, "is_file", return_value=True), patch.object(
                beacheye.ct, "CDLL", wraps=beacheye.ct.CDLL
            ) as loader:
                settings_point_catalog("FC22AR", 51)
                settings_point_catalog("FC22S", 65535)
            self.assertEqual(Path(loader.call_args.args[0]).name, "wolfeye_beacheye.dll")
            self.assertEqual(loader.call_count, 1)
        finally:
            beacheye._native.cache_clear()

    def test_measurements_follow_company_serialization_order_for_all_profiles(self) -> None:
        for model in ("FC22AR", "FC22S"):
            for build in (50, 51, 52, 100, 255, 256, 257, 306, 65535):
                catalog = settings_point_catalog(model, build)
                bi = catalog["binary"]
                ai = catalog["analog"]
                bits = bytearray((len(bi) + 7) // 8)
                for index in range(len(bi)):
                    if index % 3 == 1:
                        bits[index // 8] |= 1 << (index % 8)
                payload = (struct.pack("<H", (len(bi) << 4) | 1) + bits
                           + struct.pack("<H", (len(ai) << 4) | 2)
                           + b"".join(struct.pack("<H", index + 123) for index in range(len(ai))))
                snapshot = decode_measurements(payload, model, build)
                expected_analog = {}
                for index, (point_id, name) in enumerate(ai):
                    key = name if name not in expected_analog else f"{name} [{point_id - 1}]"
                    expected_analog[key] = float(index + 123)
                with self.subTest(model=model, build=build):
                    self.assertEqual(snapshot.binary, {name: index % 3 == 1 for index, (_, name) in enumerate(bi)})
                    self.assertEqual(snapshot.analog, expected_analog)


    def test_ar51_native_read_measurements_and_write_company_settings(self) -> None:
        self._assert_company_read_write("FC22AR", 51)

    def test_both_models_read_write_with_50_51_and_future_builds(self) -> None:
        for model in ("FC22AR", "FC22S"):
            for build in (50, 51, 52, 100, 255, 256, 257, 306, 65535):
                with self.subTest(model=model, build=build):
                    self._assert_company_read_write(model, build)

    def _assert_company_read_write(self, model: str, build: int) -> None:
        settings_payload = default_settings_file(model)[:-3]
        settings = decode_settings_payload(settings_payload, model)
        settings["sy"]["m"]["v"] = 25000
        edited_payload = patch_settings_payload(settings_payload, settings, model)
        catalog = settings_point_catalog(model, build)
        bi_count, ai_count = len(catalog["binary"]), len(catalog["analog"])
        measurements = (struct.pack("<H", (bi_count << 4) | 1) + bytes((bi_count + 7) // 8)
                        + struct.pack("<H", (ai_count << 4) | 2) + bytes(ai_count * 2))
        info = bytes((1 if model == "FC22AR" else 2, 2, 3, 4)) + struct.pack("<HH", build, 0) + b"commit51"
        listener = socket.socket()
        listener.settimeout(3)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        received = []
        server_errors = []
        replies = []
        complete = threading.Event()

        def server():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(3)
                    for response in (info, settings_payload, measurements, b"\x00", b"\x09"):
                        frame_type, payload = decode_native_frame(self._recv_frame(connection))
                        received.append((frame_type, payload))
                        connection.sendall(build_native_frame(0x01, payload[:1] + response))
            except BaseException as exc:
                server_errors.append(exc)

        def callback(event, tag, value, payload):
            if event == PROVIDER_RESPONSE:
                replies.append((tag, payload))
                if len(replies) == 5:
                    complete.set()

        worker = threading.Thread(target=server, daemon=True)
        worker.start()
        provider = NativeDataProvider(callback)
        try:
            provider.start("127.0.0.1", listener.getsockname()[1])
            for tag, frame_type, payload in ((1, 0x05, b""), (2, 0x03, b""),
                                             (3, 0x02, b"\x03"), (4, 0x04, edited_payload),
                                             (5, 0x04, edited_payload)):
                provider.request(tag, frame_type, payload)
            self.assertTrue(complete.wait(3), f"{model} build {build} read/write flow timed out")
        finally:
            provider.close()
            listener.close()
            worker.join(3)
        self.assertFalse(server_errors)
        self.assertEqual([kind for kind, _ in received], [0x05, 0x03, 0x02, 0x04, 0x04])
        self.assertEqual([payload[0] for _, payload in received], [1, 2, 3, 4, 5])
        self.assertEqual(received[2][1][1:], b"\x03")
        self.assertEqual(received[3][1][1:], edited_payload)
        self.assertEqual(decode_info(replies[0][1])["build"], build)
        self.assertEqual(decode_info(replies[0][1])["model"], model)
        self.assertEqual(replies[1][1], settings_payload)
        if model == "FC22AR" and build == 51:
            self.assertEqual(len(replies[2][1]), 300)
            self.assertEqual(ai_count, 122)
        self.assertEqual(len(decode_measurements(replies[2][1], model, build).analog), ai_count)
        self.assertEqual(replies[3:], [(4, b"\x00"), (5, b"\x09")])
        self.assertEqual(decode_settings_payload(received[3][1][1:], model)["sy"]["m"]["v"], 25000)

    def test_company_model_and_revision_aliases_are_normalized(self) -> None:
        self.assertEqual(normalize_device_model("AUTO RECLOSER"), "FC22AR")
        self.assertEqual(normalize_device_model("Sectionalizer"), "FC22S")
        self.assertEqual(normalize_device_revision("Version 108 / Revision 51"), 51)
        self.assertEqual(normalize_device_revision("V50"), 50)
        self.assertEqual(normalize_device_revision(""), 0)

    def test_lightstream_frame_round_trip(self) -> None:
        frame = build_native_frame(0x21, b"payload")
        self.assertEqual(decode_native_frame(frame), (0x21, b"payload"))

    def test_default_settings_file_round_trip(self) -> None:
        encoded = default_settings_file("FC22AR")
        settings, model = decode_settings_file(encoded)
        self.assertEqual(model, "FC22AR")
        self.assertIsInstance(settings, dict)
        self.assertTrue(settings)
        self.assertEqual(
            patch_settings_payload(encoded[:-3], settings, model),
            encode_settings_file(settings, model)[:-3]
        )

    def test_latest_company_sef_defaults_match_ui_for_both_models(self) -> None:
        ui = default_config()
        for model in ("FC22AR", "FC22S"):
            native = default_settings_json(model)
            for index, group in enumerate(native["p"]["g"]):
                for direction in ("f", "r"):
                    self.assertEqual(group["sf"][direction]["tt"], 10000)
                self.assertEqual([element["tripping_time_s"] for element in
                                  ui["protection"]["groups"][index]["sef"]["elements"]], [10.0, 10.0])

    def test_legacy_json_shape_keeps_new_revision_defaults(self) -> None:
        settings = default_settings_json("FC22AR")

        for output in settings["sy"]["io"]["o"]:
            output.pop("t", None)
        for group in settings["p"]["g"]:
            group["uv"]["u"] = group["uv"]["u"][:3]
            group["ov"] = group["ov"][:4]

        encoded = encode_settings_file(settings, "FC22AR")
        decoded, model = decode_settings_file(encoded)

        self.assertEqual(model, "FC22AR")
        self.assertEqual(len(decoded["p"]["g"][0]["uv"]["u"]), 7)
        self.assertEqual(len(decoded["p"]["g"][0]["ov"]), 8)
        self.assertEqual(decoded["sy"]["io"]["o"][0]["t"], 1000)
        self.assertEqual(decoded["sy"]["io"]["o"][7]["t"], 1000)

    def test_settings_patch_changes_only_the_selected_company_field(self) -> None:
        encoded = default_settings_file("FC22AR")
        payload = encoded[:-3]
        settings = decode_settings_payload(payload, "FC22AR")
        settings["sy"]["m"]["f"] = 1
        patched = patch_settings_payload(payload, settings, "FC22AR")
        decoded = decode_settings_payload(patched, "FC22AR")
        self.assertEqual(decoded["sy"]["m"]["f"], 1)
        self.assertEqual(len(patched), len(payload))


    def test_visible_config_round_trip_preserves_company_settings(self) -> None:
        for model in ("FC22AR", "FC22S"):
            with self.subTest(model=model):
                encoded = default_settings_file(model)
                payload = encoded[:-3]
                native = decode_settings_payload(payload, model)
                original = deepcopy(native)
                config = default_config()
                update_config_from_native(config, native)
                update_native_from_config(native, config)
                self.assertEqual(native, original)
                self.assertEqual(len(patch_settings_payload(payload, native, model)), len(payload))

    def test_visible_config_edits_reach_company_payload(self) -> None:
        model = "FC22AR"
        payload = default_settings_file(model)[:-3]
        native = decode_settings_payload(payload, model)
        config = default_config()
        update_config_from_native(config, native)
        config["general"]["measurement"]["frequency_hz"] = "60"
        config["protection"]["groups"][0]["oc"]["elements"][0]["pickup_a"] = 425
        config["protection"]["groups"][0]["oc"]["elements"][0]["tripping_time_s"] = 1.25
        config["protection"]["groups"][0]["ef"]["elements"][0]["reset_time_s"] = 1.75
        config["general"]["io"]["digital_outputs"][0]["recognition_s"] = 0.75
        config["protection"]["groups"][0]["voltage"]["uv12"]["trip_s"] = 4.25
        config["protection"]["groups"][0]["master"]["over_voltage"]["ov23"]["multiplier"] = 1.27
        fast_trip = config["protection"]["groups"][0]["oc"]["elements"][1]
        fast_trip["type"] = "IEC VI"
        fast_trip["max_mode"] = True
        fast_trip["max_current_multiplier"] = 7.25
        update_native_from_config(native, config)
        patched = patch_settings_payload(payload, native, model)
        decoded = decode_settings_payload(patched, model)
        self.assertEqual(decoded["sy"]["m"]["f"], 1)
        element = decoded["p"]["g"][0]["o"]["f"]["d"]["t"]
        self.assertEqual(element["i"], 425)
        self.assertEqual(element["tt"], 1250)
        self.assertEqual(decoded["p"]["g"][0]["e"]["f"]["d"]["t"]["tr"], 1750)
        self.assertEqual(decoded["sy"]["io"]["o"][0]["t"], 750)
        self.assertEqual(decoded["p"]["g"][0]["uv"]["u"][3]["t"], 4250)
        self.assertEqual(decoded["p"]["g"][0]["ov"][7]["u"], 127)


    def test_iec_menu_round_trip_when_profile_exposes_iec(self) -> None:
        native = default_settings_json("FC22AR")
        native["s"]["i"] = {
            "as": 1,
            "is": 2,
            "cs": 1,
            "ia": 1,
            "t": 1,
            "aa": 12,
            "o": 3,
            "b": list(range(100, 108)),
            "i1": {
                "c": 4,
                "r": 5000,
                "m": 1,
                "as": 1,
                "s": 1,
                "a": 9,
                "at": 2000,
                "rt": 3000,
            },
            "i4": {"t": [1000, 2000, 3000, 4000], "k": 12, "w": 8},
        }
        original = deepcopy(native)
        config = default_config()

        update_config_from_native(config, native)
        update_native_from_config(native, config)

        self.assertEqual(native, original)
        config["general"]["scada"]["iec"]["iec104"]["timeout_2_s"] = 7.5
        update_native_from_config(native, config)
        self.assertEqual(native["s"]["i"]["i4"]["t"][2], 7500)

    def test_measurement_decoder_uses_exact_revision_51_point_profile(self) -> None:
        payload = (
            struct.pack("<H", (410 << 4) | 0x01)
            + bytes(52)
            + struct.pack("<H", (122 << 4) | 0x02)
            + b"".join(struct.pack("<H", value) for value in range(122))
        )
        self.assertEqual(len(payload), 300)
        snapshot = decode_measurements(payload, "FC22AR", 51)
        self.assertEqual(len(snapshot.binary), 410)
        self.assertEqual(len(snapshot.analog), 122)
        self.assertIn("Open", snapshot.binary)
        self.assertIn("Closed", snapshot.binary)
        self.assertEqual(snapshot.analog["Ia"], 0.0)
        self.assertEqual(snapshot.analog["Uab"], 11.0)
        self.assertIn("Battery Voltage", snapshot.analog)

    def test_different_measurement_profile_keeps_wire_values_without_wrong_names(self) -> None:
        payload = (
            struct.pack("<H", (394 << 4) | 0x01)
            + bytes(50)
            + struct.pack("<H", (121 << 4) | 0x02)
            + bytes(242)
        )
        snapshot = decode_measurements(payload, "FC22AR", 51)
        self.assertEqual(len(snapshot.binary), 394)
        self.assertEqual(len(snapshot.analog), 121)
        self.assertEqual(snapshot.analog["AI 120"], 0)
        self.assertNotIn("Ia", snapshot.analog)

    def test_unknown_device_profile_uses_explicit_generic_names(self) -> None:
        payload = (
            struct.pack("<H", (8 << 4) | 0x01)
            + b"\x05"
            + struct.pack("<H", (2 << 4) | 0x02)
            + struct.pack("<HH", 10, 20)
        )
        snapshot = decode_measurements(payload)
        self.assertEqual(snapshot.binary["BI 0"], True)
        self.assertEqual(snapshot.binary["BI 2"], True)
        self.assertEqual(snapshot.analog, {"AI 0": 10.0, "AI 1": 20.0})

    def test_measurement_decoder_still_rejects_incomplete_payload(self) -> None:
        with self.assertRaises(ValueError):
            decode_measurements(struct.pack("<H", (16 << 4) | 0x02) + b"\0", "FC22AR", 50)


    def test_partial_measurement_profile_retains_every_advertised_point(self) -> None:
        payload = (
            struct.pack("<H", (15 << 4) | 0x01)
            + bytes([0b00001000, 0])
            + struct.pack("<H", (15 << 4) | 0x02)
            + b"".join(struct.pack("<H", value) for value in range(15))
        )
        snapshot = decode_measurements(payload, "FC22AR", 100)
        self.assertEqual(len(snapshot.binary), 15)
        self.assertTrue(snapshot.binary["BI 3"])
        self.assertEqual(snapshot.analog["AI 14"], 14)

    def test_event_timestamp_uses_company_tehran_offset(self) -> None:
        payload = struct.pack("<H", 0x4000) + (12_600_000).to_bytes(6, "little")
        event = decode_events(payload, "FC22AR", 50)[0]
        self.assertEqual(event.timestamp, datetime.fromtimestamp(0))

    def test_events_reject_incomplete_device_tail(self) -> None:
        event = struct.pack("<H", 0) + (12_600_000).to_bytes(6, "little")
        payload = event * 639 + b"\xaa\xbb"
        self.assertEqual(len(payload), 5114)
        with self.assertRaises(ValueError):
            decode_events(payload, "FC22AR", 50)

    def test_counter_event_preserves_32_bit_value(self) -> None:
        payload = (
            struct.pack("<H", (2 << 12) | 3)
            + (12_600_000).to_bytes(6, "little")
            + struct.pack("<I", 0x89ABCDEF)
        )

        event = decode_events(payload, "FC22AR", 50)[0]

        self.assertEqual(event.kind, "Counter")
        self.assertEqual(event.value, str(0x89ABCDEF))


    def test_serialized_mixed_events_and_empty_slots_for_both_models(self) -> None:
        bi = struct.pack("<H", 0x4000) + (12_600_000).to_bytes(6, "little")
        ai = struct.pack("<H", 0x1003) + (12_601_000).to_bytes(6, "little") + struct.pack("<H", 65535)
        cc = struct.pack("<H", 0x2003) + (12_602_000).to_bytes(6, "little") + struct.pack("<I", 0xFFFFFFFF)
        for model in ("FC22AR", "FC22S"):
            for build in (50, 51, 52, 256, 65535):
                for hint in ("company",):
                    with self.subTest(model=model, build=build, hint=hint):
                        events = decode_events(bi + ai + cc + bytes(8), model, build)
                        self.assertEqual([event.kind for event in events], ["Binary", "Analog", "Counter"])
                        self.assertEqual([event.value for event in events], ["ON", "65535", "4294967295"])
                self.assertEqual(decode_events(bytes(5512), model, build), [])
                self.assertEqual(decode_events(b"", model, build), [])
                self.assertEqual(decode_events(bytes(8), model, build), [])

    def test_incomplete_analog_and_counter_events_are_not_silently_lost(self) -> None:
        for size in range(1, 8):
            with self.subTest(short=size), self.assertRaises(ValueError):
                decode_events(bytes(size), "FC22AR", 51)
        for kind, length in ((1, 10), (2, 12)):
            for size in range(8, length):
                payload = struct.pack("<H", kind << 12) + (12_600_000).to_bytes(6, "little") + bytes(size - 8)
                with self.subTest(kind=kind, size=size), self.assertRaises(ValueError):
                    decode_events(payload, "FC22AR", 51)



    def test_provider_receives_large_fragmented_events_with_crc_and_sequence_checks(self) -> None:
        # The reported 5512-byte failure is reproduced through the socket,
        # not only by calling a decoder with an already assembled payload.
        payload = struct.pack("<H?5x", 344, False) + b"".join(
            struct.pack("<QIHBx", 12_600_000 + index * 1000, index, 0, 0)
            for index in range(344)
        )
        def wire_frame(body):
            header = struct.pack("<HB", len(body), 1)
            return b"A$" + header + body + struct.pack("<H", crc_hqx(header + body, 0xFFFF))
        for length in (5120, 5121, 5512, 8192, 65535):
            body = bytes(length)
            self.assertEqual(decode_native_frame(wire_frame(body)), (1, body))
        self.assertEqual(decode_native_frame(build_native_frame(7, bytes(5512))), (7, bytes(5512)))
        self.assertEqual(decode_native_frame(wire_frame(payload)), (1, payload))
        for sequenced in (True,):
            listener = socket.socket()
            listener.settimeout(3)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            replies, errors = [], []
            complete = threading.Event()
            def server():
                try:
                    with listener.accept()[0] as connection:
                        connection.settimeout(3)
                        _, request = decode_native_frame(self._recv_frame(connection))
                        body = request[:1] + payload
                        frame = wire_frame(body)
                        damaged = frame[:-1] + bytes((frame[-1] ^ 0xFF,))
                        connection.sendall(damaged)
                        if sequenced:
                            wrong_sequence = wire_frame(bytes((request[0] % 255 + 1,)) + payload)
                            connection.sendall(wrong_sequence)
                        for start in range(0, len(frame), 137):
                            connection.sendall(frame[start:start + 137])
                        complete.wait(3)
                except BaseException as exc:
                    errors.append(exc)
            def callback(event, tag, value, body):
                if event == PROVIDER_RESPONSE:
                    replies.append((tag, body))
                    complete.set()
            worker = threading.Thread(target=server, daemon=True)
            worker.start()
            provider = NativeDataProvider(callback)
            try:
                provider.start("127.0.0.1", listener.getsockname()[1])
                provider.request(5, 7)
                self.assertTrue(complete.wait(3), "events response timed out")
                self.assertEqual(replies, [(5, payload)])
                self.assertEqual(replies[0][1], payload)
            finally:
                provider.close()
                listener.close()
                worker.join(3)
            self.assertFalse(errors)

    def test_unknown_revision_uses_serialized_events_not_v50_ring_layout(self) -> None:
        event = struct.pack("<H", 0) + (12_600_000).to_bytes(6, "little")
        events = decode_events(event * 3, "AUTO RECLOSER", 0)
        self.assertEqual(len(events), 3)
        self.assertTrue(all(record.point == "Dummy Control" for record in events))




    def test_native_provider_owns_tcp_framing_and_sequence(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        received: list[tuple[int, bytes]] = []
        server_error: list[BaseException] = []

        def server() -> None:
            try:
                connection, _address = listener.accept()
                with connection:
                    frame = self._recv_frame(connection)
                    frame_type, payload = decode_native_frame(frame)
                    received.append((frame_type, payload))
                    connection.sendall(
                        build_native_frame(frame_type, payload[:1] + b"reply")
                    )
            except BaseException as exc:
                server_error.append(exc)

        worker = threading.Thread(target=server, daemon=True)
        worker.start()
        completed = threading.Event()
        events: list[tuple[int, int, int, bytes]] = []

        def callback(event: int, tag: int, value: int, payload: bytes) -> None:
            events.append((event, tag, value, payload))
            if event == PROVIDER_RESPONSE:
                completed.set()

        provider = NativeDataProvider(callback)
        try:
            provider.start("127.0.0.1", port)
            provider.request(42, 0x21, b"payload")
            self.assertTrue(completed.wait(3), "native provider response timed out")
        finally:
            provider.close()
            listener.close()
            worker.join(3)

        self.assertFalse(server_error)
        self.assertEqual(received[0][0], 0x21)
        self.assertEqual(received[0][1][1:], b"payload")
        self.assertIn((PROVIDER_RESPONSE, 42, 0x21, b"reply"), events)


    def test_failed_connection_reports_endpoint_and_winsock_error(self) -> None:
        # Keep a bound but non-listening socket so the target cannot race with
        # another service between choosing the port and testing the refusal.
        reservation = socket.socket()
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
        provider = NativeDataProvider(lambda *_args: None)
        try:
            # Windows can time out before completing its refusal retries.
            with self.assertRaisesRegex(OSError, f"127.0.0.1:{port}.*Winsock (10060|10061)") as caught:
                provider.start("127.0.0.1", port, timeout_ms=2000)
            self.assertIn("timed out" if "10060" in str(caught.exception) else "refused", str(caught.exception))
        finally:
            provider.close()
            reservation.close()

    def test_device_service_connects_and_reads_info_settings_without_http(self) -> None:
        from wolfeye.services.device_service import DeviceService
        info = bytes((1, 100, 2, 2)) + struct.pack("<HH", 51, 0) + b"commit51"
        settings = default_settings_file("FC22AR")[:-3]
        listener = socket.socket()
        listener.settimeout(3)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        completed, release = threading.Event(), threading.Event()
        received, errors = [], []
        service = DeviceService()
        original_response = service._handle_native_response
        def response(command, frame_type, payload):
            original_response(command, frame_type, payload)
            if command == "settings":
                received.append(payload)
                completed.set()
        def server():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(3)
                    for expected_kind, body in ((5, info), (3, settings)):
                        kind, request = decode_native_frame(self._recv_frame(connection))
                        if kind != expected_kind:
                            raise AssertionError((kind, expected_kind))
                        connection.sendall(build_native_frame(1, request[:1] + body))
                    release.wait(3)
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=server, daemon=True)
        worker.start()
        try:
            with patch("wolfeye.services.device_service.WOLFEYE_PORT", listener.getsockname()[1]), patch.object(service, "_handle_native_response", side_effect=response):
                service._connect_worker("127.0.0.1")
                self.assertTrue(completed.wait(3), "INFO/settings handshake timed out")
                self.assertTrue(service.connected)
                self.assertTrue(service._handshake_complete)
                self.assertEqual((service.info.model, service.info.build, service.info.firmware), ("FC22AR", 51, 100))
                self.assertEqual(received, [settings])
        finally:
            release.set()
            service.disconnect_device()
            service._provider.close()
            listener.close()
            worker.join(3)
        self.assertFalse(errors)

    def test_native_provider_owns_complete_update_flow(self) -> None:
        body = b"prefix DFHB-VER=FC22AR.1.3.50.commit\0firmware"
        image = body + struct.pack("<H", crc_hqx(body, 0xFFFF))
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        frames: list[tuple[int, bytes]] = []
        server_error: list[BaseException] = []

        def server() -> None:
            statuses = (0x00, 0x05, 0x09, 0x02)
            try:
                connection, _address = listener.accept()
                with connection:
                    for status in statuses:
                        frame_type, payload = decode_native_frame(
                            self._recv_frame(connection)
                        )
                        frames.append((frame_type, payload))
                        connection.sendall(
                            build_native_frame(frame_type, payload[:1] + bytes((status,)))
                        )
            except BaseException as exc:
                server_error.append(exc)

        worker = threading.Thread(target=server, daemon=True)
        worker.start()
        completed = threading.Event()
        results: list[tuple[int, int, bytes]] = []

        def callback(event: int, tag: int, value: int, payload: bytes) -> None:
            if event == PROVIDER_UPDATE_FINISHED:
                results.append((tag, value, payload))
                completed.set()

        provider = NativeDataProvider(callback)
        try:
            provider.start("127.0.0.1", port)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "firmware.bin"
                path.write_bytes(image)
                provider.update_file(PROVIDER_FIRMWARE, str(path), 3, 2)
                self.assertTrue(completed.wait(3), "native update flow timed out")
        finally:
            provider.close()
            listener.close()
            worker.join(3)

        self.assertFalse(server_error)
        self.assertEqual([frame[0] for frame in frames], [0x0B, 0x09, 0x0B, 0x0D])
        self.assertEqual(frames[0][1][1:], image[-2:])
        self.assertEqual(frames[1][1][1], 0x03)
        self.assertEqual(frames[1][1][2:], image)
        self.assertEqual(results[0][0:2], (PROVIDER_FIRMWARE, 1))

    @staticmethod
    def _recv_frame(connection: socket.socket) -> bytes:
        data = bytearray()
        while len(data) < 4:
            chunk = connection.recv(8192)
            if not chunk:
                raise EOFError("native provider closed before the frame header")
            data.extend(chunk)
        size = struct.unpack_from("<H", data, 2)[0] + 7
        while len(data) < size:
            chunk = connection.recv(8192)
            if not chunk:
                raise EOFError("native provider closed before the complete frame")
            data.extend(chunk)
        return bytes(data[:size])


if __name__ == "__main__":
    unittest.main()
