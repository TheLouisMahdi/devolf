"""No file-chunk-size policy may reject complete measurement/event frames."""
import socket
import struct
import threading
import unittest

from wolfeye.services import beacheye
from wolfeye.services.beacheye import (
    NativeDataProvider, PROVIDER_RESPONSE, build_native_frame,
    decode_native_frame, decode_measurements, decode_events,
)


def receive_frame(connection):
    def exact(count):
        result = bytearray()
        while len(result) < count:
            part = connection.recv(count - len(result))
            if not part:
                raise EOFError("Peer closed during a frame")
            result.extend(part)
        return bytes(result)
    header = exact(5)
    length = struct.unpack_from("<H", header, 2)[0]
    return decode_native_frame(header + exact(length + 2))


class PayloadTransportTests(unittest.TestCase):
    def test_frames_round_trip_full_wire_length_and_crc(self):
        for length in (0, 5112, 5120, 5121, 5512, 8192, 65534, 65535):
            with self.subTest(length=length):
                body = bytes(index % 251 for index in range(length))
                frame = build_native_frame(4, body)
                self.assertEqual(decode_native_frame(frame), (4, body))
                with self.assertRaises(ValueError):
                    decode_native_frame(frame[:-1] + bytes((frame[-1] ^ 1,)))
        with self.assertRaisesRegex(ValueError, "two-byte length"):
            build_native_frame(4, bytes(65536))
        # Native callers also cannot truncate a large size into the wire header.
        source = beacheye.ct.create_string_buffer(b"x")
        output = (beacheye.ct.c_ubyte * 16)()
        for length in (65536, beacheye.ct.c_size_t(-1).value):
            self.assertLess(beacheye._native().be_frame_build(4, source, length, output, 16), 0)

    def test_provider_sends_large_requests_and_reserves_only_native_sequence(self):
        for sequenced in (True,):
            with self.subTest(sequenced=sequenced):
                maximum = 65534
                bodies = [bytes(index % 251 for index in range(size))
                          for size in (5112, 5120, 5121, 5512, 8192, maximum)]
                listener = socket.socket()
                listener.settimeout(5)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                complete, finish = threading.Event(), threading.Event()
                replies, errors = [], []
                def server():
                    try:
                        with listener.accept()[0] as connection:
                            connection.settimeout(5)
                            for body in bodies:
                                frame_type, request = receive_frame(connection)
                                self.assertEqual(frame_type, 4)
                                self.assertEqual(request[1:], body)
                                response = request[:1] + b"\x00"
                                connection.sendall(build_native_frame(1, response))
                            finish.wait(5)
                    except BaseException as exc:
                        errors.append(exc)
                        complete.set()
                def callback(event, tag, _value, body):
                    if event == PROVIDER_RESPONSE:
                        replies.append((tag, body))
                        complete.set()
                worker = threading.Thread(target=server, daemon=True)
                worker.start()
                provider = NativeDataProvider(callback)
                try:
                    provider.start("127.0.0.1", listener.getsockname()[1])
                    with self.assertRaisesRegex(OSError, "two-byte length"):
                        provider.request(99, 4, bytes(maximum + 1))
                    for tag, body in enumerate(bodies, 10):
                        complete.clear()
                        provider.request(tag, 4, body)
                        self.assertTrue(complete.wait(5), f"No response to {len(body)} bytes")
                        self.assertFalse(errors)
                        self.assertEqual(replies[-1], (tag, b"\x00"))
                finally:
                    finish.set()
                    provider.close()
                    listener.close()
                    worker.join(5)
                self.assertFalse(errors)

    def test_measurement_blocks_have_no_fixed_count_or_file_chunk_limit(self):
        # Eight AI blocks fill the largest even-sized native response body.
        block = struct.pack("<H", (4095 << 4) | 2) + struct.pack("<4095H", *range(4095))
        last = struct.pack("<H", (4094 << 4) | 2) + struct.pack("<4094H", *range(4094))
        data = block * 7 + last
        self.assertEqual(len(data), 65534)
        for model in ("FC22AR", "FC22S"):
            snapshot = decode_measurements(data, model, 51)
            self.assertEqual(len(snapshot.analog), 32759)
            self.assertEqual(snapshot.analog["AI 4095"], 0)
            self.assertEqual(snapshot.analog["AI 32758"], 4093)
            self.assertNotIn("Ia", snapshot.analog)
            empty = struct.pack("<HHH", 1, 2, 4)
            self.assertEqual(decode_measurements(empty, model, 51).analog, {})
        company_count = len(beacheye.settings_point_catalog("FC22AR", 51)["analog"])
        block = struct.pack("<H", (company_count << 4) | 2) + struct.pack(f"<{company_count}H", *range(company_count))
        repeated = decode_measurements(block * 3, "FC22AR", 51)
        self.assertEqual(len(repeated.analog), company_count * 3)
        self.assertEqual(repeated.analog[f"AI {company_count * 3 - 1}"], company_count - 1)

    def test_fragmented_measurements_and_events_arrive_without_size_rejection(self):
        measurements = struct.pack("<H", (4095 << 4) | 2) + struct.pack("<4095H", *range(4095))
        event = struct.pack("<H", 0x4000) + (12_600_000).to_bytes(6, "little")
        events = event * 8191
        for sequenced in (True,):
            listener = socket.socket()
            listener.settimeout(5)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            complete, finish = threading.Event(), threading.Event()
            replies, errors = [], []
            def server():
                try:
                    with listener.accept()[0] as connection:
                        connection.settimeout(5)
                        for body in (measurements, events):
                            _, request = receive_frame(connection)
                            data = request[:1] + body
                            frame = build_native_frame(1, data)
                            for start in range(0, len(frame), 137):
                                connection.sendall(frame[start:start + 137])
                        finish.wait(5)
                except BaseException as exc:
                    errors.append(exc)
                    complete.set()
            def callback(event, tag, _value, body):
                if event == PROVIDER_RESPONSE:
                    replies.append((tag, body))
                    complete.set()
            worker = threading.Thread(target=server, daemon=True)
            worker.start()
            provider = NativeDataProvider(callback)
            try:
                provider.start("127.0.0.1", listener.getsockname()[1])
                for tag, frame_type, body in ((2, 2, measurements), (5, 7, events)):
                    complete.clear()
                    provider.request(tag, frame_type)
                    self.assertTrue(complete.wait(5))
                    self.assertFalse(errors)
                    self.assertEqual(replies[-1], (tag, body))
                for model in ("FC22AR", "FC22S"):
                    self.assertEqual(len(decode_measurements(replies[0][1], model, 51).analog), 4095)
                    self.assertEqual(len(decode_events(replies[1][1], model, 51)), 8191)
            finally:
                finish.set()
                provider.close()
                listener.close()
                worker.join(5)
            self.assertFalse(errors)
