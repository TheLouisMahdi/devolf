import unittest
from binascii import crc_hqx
import struct
import socket
import tempfile
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from wolfeye.services.beacheye import (
    PROVIDER_FIRMWARE,
    PROVIDER_RESPONSE,
    PROVIDER_UPDATE_FINISHED,
    NativeDataProvider,
    build_native_frame,
    decode_native_frame,
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
            patch_settings_payload(encoded[:-3], settings, model), encoded[:-3]
        )

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
        self.assertEqual(sum(a != b for a, b in zip(payload, patched)), 1)

    def test_pre_menu_split_revision_50_settings_round_trip(self) -> None:
        current = default_settings_file("FC22AR")[:-3]
        self.assertEqual(len(current), 3439)
        legacy = b"".join(
            (
                current[:2348],
                current[2504:3038],
                current[3038:3204],
                current[3236:3268],
                current[3268:3381],
                current[3389:3439],
            )
        )
        self.assertEqual(len(legacy), 3243)

        settings = decode_settings_payload(legacy, "FC22AR")
        self.assertEqual(patch_settings_payload(legacy, settings, "FC22AR"), legacy)
        settings["sy"]["m"]["f"] = 1
        patched = patch_settings_payload(legacy, settings, "FC22AR")

        self.assertEqual(len(patched), 3243)
        self.assertEqual(decode_settings_payload(patched, "FC22AR")["sy"]["m"]["f"], 1)

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
                self.assertEqual(patch_settings_payload(payload, native, model), payload)

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
        self.assertEqual(native["p"]["g"][0]["cm"][0], 725)
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
        self.assertEqual(decoded["p"]["g"][0]["o"]["f"]["f"]["t"]["mm"], 1)

    def test_all_functions_and_sectionalizer_state_round_trip(self) -> None:
        model = "FC22S"
        payload = default_settings_file(model)[:-3]
        native = decode_settings_payload(payload, model)
        self.assertEqual(len(native["sy"]["fn"]), 16)
        catalog = settings_point_catalog(model, 50)
        self.assertTrue(catalog["binary"])
        self.assertTrue(catalog["analog"])

        config = default_config()
        update_config_from_native(config, native)
        function = config["general"]["system"]["functions"][15]
        function.update(
            enabled=True,
            value_type="ANALOG",
            analog_operator="LESS",
            analog_value_a=catalog["analog"][0][0],
            analog_compared_to=1234,
            time_s=1.25,
            action="CLOSE",
        )
        config["protection"]["groups"][0]["sectionalizing"]["state"] = "TRIP/LOCK"
        config["general"]["io"]["digital_inputs"]["validation_time_s"] = 0.128
        output = config["general"]["io"]["digital_outputs"][0]
        output["when"] = catalog["binary"][0][0]
        output["then"] = "PULSE ON"
        output["for_s"] = 2.5

        update_native_from_config(native, config)
        patched = patch_settings_payload(payload, native, model)
        decoded = decode_settings_payload(patched, model)
        raw_function = decoded["sy"]["fn"][15]
        self.assertEqual(raw_function["t"], 1250)
        self.assertEqual(raw_function["v"], 1234)
        self.assertEqual(raw_function["o"][3], catalog["analog"][0][0])
        self.assertEqual(raw_function["s"], [1, 0, 1, 0, 1, 2])
        self.assertEqual(decoded["p"]["g"][0]["sc"]["s"], 1)
        self.assertEqual(decoded["sy"]["io"]["i"]["v"], 128)
        self.assertEqual(decoded["sy"]["io"]["o"][0]["i"], catalog["binary"][0][0])
        self.assertEqual(decoded["sy"]["io"]["o"][0]["o"], 2500)

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
            struct.pack("<H", (394 << 4) | 0x01)
            + bytes(50)
            + struct.pack("<H", (121 << 4) | 0x02)
            + b"".join(struct.pack("<H", value) for value in range(121))
        )
        self.assertEqual(len(payload), 296)
        snapshot = decode_measurements(payload, "FC22AR", 51)
        self.assertEqual(len(snapshot.binary), 394)
        self.assertEqual(len(snapshot.analog), 121)
        self.assertIn("Open", snapshot.binary)
        self.assertIn("Closed", snapshot.binary)
        self.assertEqual(snapshot.analog["Ia"], 0.0)
        self.assertEqual(snapshot.analog["Uab"], 11.0)
        self.assertIn("Battery Voltage", snapshot.analog)

    def test_measurement_decoder_rejects_profile_from_another_known_revision(self) -> None:
        payload = (
            struct.pack("<H", (448 << 4) | 0x01)
            + bytes(56)
            + struct.pack("<H", (120 << 4) | 0x02)
            + bytes(240)
        )
        with self.assertRaisesRegex(ValueError, "does not match FC22AR revision 51"):
            decode_measurements(payload, "FC22AR", 51)

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

    def test_measurement_decoder_accepts_revision_50_legacy_byte_binaries(self) -> None:
        binary = bytes((index & 1 for index in range(90)))
        analog = b"".join(struct.pack("<H", index) for index in range(54))
        payload = (
            struct.pack("<H", (90 << 4) | 0x01)
            + binary
            + struct.pack("<H", (54 << 4) | 0x02)
            + analog
        )
        snapshot = decode_measurements(payload, "FC22S", 50)
        self.assertEqual(len(snapshot.binary), 90)
        self.assertEqual(len(snapshot.analog), 54)
        self.assertEqual(
            list(snapshot.binary)[:4],
            ["Lockout(Any)", "Remote Control", "Prot initiated", "Pickup"],
        )
        self.assertFalse(
            any(name.startswith(("BI ", "AI ")) for name in (*snapshot.binary, *snapshot.analog))
        )
        self.assertEqual(snapshot.analog["Ia"], 0.0)

    def test_partial_native_measurement_profile_is_rejected_for_known_device(self) -> None:
        payload = (
            struct.pack("<H", (15 << 4) | 0x01)
            + bytes([0b00001000, 0])
            + struct.pack("<H", (15 << 4) | 0x02)
            + b"".join(struct.pack("<H", value) for value in range(15))
        )
        with self.assertRaisesRegex(ValueError, "does not match FC22AR revision 100"):
            decode_measurements(payload, "FC22AR", 100)

    def test_event_timestamp_uses_company_tehran_offset(self) -> None:
        payload = struct.pack("<H", 0x4000) + (12_600_000).to_bytes(6, "little")
        event = decode_events(payload, "FC22AR", 50)[0]
        self.assertEqual(event.timestamp, datetime.fromtimestamp(0))

    def test_events_ignore_short_device_tail_like_company_decoder(self) -> None:
        event = struct.pack("<H", 0) + (12_600_000).to_bytes(6, "little")
        payload = event * 639 + b"\xaa\xbb"
        self.assertEqual(len(payload), 5114)
        self.assertEqual(len(decode_events(payload, "FC22AR", 50)), 639)

    def test_counter_event_preserves_32_bit_value(self) -> None:
        payload = (
            struct.pack("<H", (2 << 12) | 3)
            + (12_600_000).to_bytes(6, "little")
            + struct.pack("<I", 0x89ABCDEF)
        )

        event = decode_events(payload, "FC22AR", 50)[0]

        self.assertEqual(event.kind, "Counter")
        self.assertEqual(event.value, str(0x89ABCDEF))

    def test_unknown_revision_uses_serialized_events_not_v50_ring_layout(self) -> None:
        event = struct.pack("<H", 0) + (12_600_000).to_bytes(6, "little")
        events = decode_events(event * 3, "AUTO RECLOSER", 0)
        self.assertEqual(len(events), 3)
        self.assertTrue(all(record.point == "Dummy Control" for record in events))

    def test_revision_50_raw_events_ring_is_decoded_newest_first(self) -> None:
        records = []
        for index in range(3):
            records.append(
                struct.pack("<QIHBx", 12_600_000 + index * 1000, index, index + 1, 0)
            )
        payload = struct.pack("<H?5x", 3, False) + b"".join(records) + bytes(16)
        events = decode_events(payload, "FC22AR", 50)
        self.assertEqual([event.value for event in events], ["ON", "ON", "OFF"])
        self.assertEqual([event.timestamp for event in events], [
            datetime.fromtimestamp(2), datetime.fromtimestamp(1), datetime.fromtimestamp(0)
        ])

    def test_raw_events_ring_is_detected_when_reported_build_is_new(self) -> None:
        records = [
            struct.pack("<QIHBx", 12_600_000 + index * 1000, index, index, 0)
            for index in range(3)
        ]
        payload = struct.pack("<H?5x", 3, False) + b"".join(records) + bytes(16)
        events = decode_events(payload, "FC22AR", 100)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].timestamp, datetime.fromtimestamp(2))

    def test_revision_50_settings_round_trip_is_byte_exact(self) -> None:
        payload = bytes(range(256)) * 16 + bytes(range(12))
        settings = decode_settings_payload(payload, "FC22S")
        self.assertEqual(patch_settings_payload(payload, settings, "FC22S"), payload)

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

    def test_native_provider_supports_legacy_frames_without_sequence(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        completed = threading.Event()
        received: list[tuple[int, bytes]] = []
        events: list[tuple[int, int, int, bytes]] = []

        def server() -> None:
            connection, _address = listener.accept()
            with connection:
                frame_type, payload = decode_native_frame(
                    self._recv_frame(connection)
                )
                received.append((frame_type, payload))
                connection.sendall(build_native_frame(0x05, b"legacy"))

        worker = threading.Thread(target=server, daemon=True)
        worker.start()

        def callback(event: int, tag: int, value: int, payload: bytes) -> None:
            events.append((event, tag, value, payload))
            if event == PROVIDER_RESPONSE:
                completed.set()

        provider = NativeDataProvider(callback)
        try:
            provider.start("127.0.0.1", port, legacy_protocol=True)
            provider.request(11, 0x01, b"\x03")
            self.assertTrue(completed.wait(3), "legacy provider response timed out")
        finally:
            provider.close()
            listener.close()
            worker.join(3)

        self.assertEqual(received, [(0x01, b"\x03")])
        self.assertIn((PROVIDER_RESPONSE, 11, 0x05, b"legacy"), events)

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
