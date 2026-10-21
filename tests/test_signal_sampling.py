"""WolfEye Python decoding through BeachEye transport and the signal viewer."""
import math
import os
import socket
import struct
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from wolfeye.models import DeviceInfo
from wolfeye.qt import QApplication
from wolfeye.services import beacheye, wolfeye as core
from wolfeye.services.device_service import DeviceService, FRAME_INFO, FRAME_SIGNAL, FRAME_ADC
from wolfeye.widgets.main_window import MainWindow
from wolfeye.widgets.pages import SignalPage


def signal_payload(samples, extra_channels=0):
    return struct.pack(f"<{(10 + extra_channels) * samples}f", *(
        channel * 100 + sample / samples
        for channel in range(10 + extra_channels) for sample in range(samples)
    ))


def adc_payload(samples, cycles=1):
    words = []
    for cycle in range(cycles):
        for half in range(2):
            indices = range(half * samples // 2, (half + 1) * samples // 2)
            for sample in indices:
                words.extend(channel * 1000 + cycle * 100 + sample for channel in range(4, 10))
            for sample in indices:
                words.extend(channel * 1000 + cycle * 100 + sample for channel in range(4))
    return struct.pack(f"<{len(words)}H", *words)


class SignalDecoderTests(unittest.TestCase):
    def test_signal_and_adc_do_not_load_any_dll(self):
        with patch("ctypes.CDLL", side_effect=OSError("wrong architecture or missing DLL")):
            self.assertEqual(len(core.decode_signal(signal_payload(32), 32)[0]), 32)
            self.assertEqual(len(core.decode_adc(adc_payload(64), 64)[0]), 64)
        self.assertFalse(hasattr(core, "_native"))
        self.assertIs(beacheye.decode_signal, core.decode_signal)

    def test_both_signal_strides_preserve_every_channel_and_sample(self):
        for samples in (32, 64):
            for extras in (0, 2):
                with self.subTest(samples=samples, extras=extras):
                    channels = beacheye.decode_signal(signal_payload(samples, extras), samples)
                    self.assertEqual(channels, [
                        [channel * 100 + sample / samples for sample in range(samples)]
                        for channel in range(10)
                    ])

    def test_32_sample_fixed_size_response_uses_only_company_prefix(self):
        for length in (2560, 3072):
            # Unused tail may contain stale/non-finite memory. INFO, rather
            # than response length, chooses the stride of the displayed data.
            body = signal_payload(32) + struct.pack("<f", float("nan")) * ((length - 1280) // 4)
            self.assertEqual(beacheye.decode_signal(body, 32), [
                [channel * 100 + sample / 32 for sample in range(32)]
                for channel in range(10)
            ])

    def test_wrong_profile_and_malformed_signal_are_rejected(self):
        for samples in (32, 64):
            for length in (0, 10 * samples * 4 - 4, 10 * samples * 4 + 4, 12 * samples * 4 + 4):
                with self.subTest(samples=samples, length=length), self.assertRaises(ValueError):
                    beacheye.decode_signal(bytes(length), samples)
            if samples == 64:
                with self.assertRaises(ValueError):
                    beacheye.decode_signal(signal_payload(32), samples)

    def test_nonfinite_signal_rejected_and_finite_spikes_retained(self):
        for samples in (32, 64):
            for value in (float("nan"), float("inf"), -float("inf"), 10000.0):
                body = bytearray(signal_payload(samples))
                struct.pack_into("<f", body, (6 * samples + 21) * 4, value)
                if math.isfinite(value):
                    self.assertEqual(beacheye.decode_signal(bytes(body), samples)[6][21], value)
                else:
                    with self.assertRaisesRegex(ValueError, "non-finite"):
                        beacheye.decode_signal(bytes(body), samples)

    def test_adc_both_profiles_and_multiple_cycles_without_overwrite(self):
        for samples in (32, 64):
            for cycles in (1, 2, 12):
                with self.subTest(samples=samples, cycles=cycles):
                    channels = beacheye.decode_adc(adc_payload(samples, cycles), samples)
                    self.assertEqual(channels, [
                        [channel * 1000 + cycle * 100 + sample
                         for cycle in range(cycles) for sample in range(samples)]
                        for channel in range(10)
                    ])

    def test_adc_rejects_partial_cycle_and_invalid_profile(self):
        for samples in (32, 64):
            for body in (b"", b"\0", adc_payload(samples)[:-2]):
                with self.assertRaises(ValueError):
                    beacheye.decode_adc(body, samples)
        for samples in (0, 16, 128):
            with self.assertRaises(ValueError):
                beacheye.decode_adc(b"", samples)
            with self.assertRaises(ValueError):
                beacheye.decode_signal(b"", samples)

    def test_adc_preserves_unsigned_counts(self):
        for samples in (32, 64):
            body = struct.pack(f"<{10 * samples}H", *([65535] * (10 * samples)))
            self.assertEqual(beacheye.decode_adc(body, samples), [[65535.0] * samples for _ in range(10)])

    def test_service_accepts_padded_32_sample_response(self):
        service = DeviceService()
        self.addCleanup(service._provider.close)
        service.info.flags = 3
        received, errors = [], []
        service.signal_received.connect(received.append)
        service.message.connect(lambda message, level: errors.append(message) if level == "error" else None)
        with patch.object(service, "_save_signal_diagnostic", return_value=""):
            service._handle_native_response("signal", FRAME_SIGNAL, signal_payload(32) + bytes(1280))
        self.assertEqual(len(received), 1)
        self.assertEqual(len(received[0][0]), 32)
        self.assertEqual(received[0][9][0], 900)
        self.assertEqual(errors, [])

    def test_info_flag_drives_signal_and_adc_and_resets_for_next_device(self):
        service = DeviceService()
        self.addCleanup(service._provider.close)
        signals, adcs, errors = [], [], []
        service.signal_received.connect(signals.append)
        service.adc_received.connect(adcs.append)
        service.message.connect(lambda text, level: errors.append(text) if level == "error" else None)
        with patch.object(service, "_send_native_request"), patch.object(service, "_save_signal_diagnostic", return_value=""):
            for model in (1, 2):
                for flags, samples in ((0, 64), (1, 64), (2, 32), (3, 32), (0, 64)):
                    info = bytes((model, 1, 2, 3)) + struct.pack("<HH", 51, flags) + b"commit00"
                    service._handle_native_response("info", FRAME_INFO, info)
                    self.assertEqual(service.info.signal_samples, samples)
                    service._handle_native_response("signal", FRAME_SIGNAL, signal_payload(samples))
                    service._handle_native_response("adc", FRAME_ADC, adc_payload(samples))
                    self.assertEqual(signals[-1][9][-1], 900 + (samples - 1) / samples)
                    self.assertEqual(adcs[-1][9][-1], 9000 + samples - 1)
            self.assertEqual(len(signals), 10)
            self.assertEqual(len(adcs), 10)
            self.assertEqual(errors, [])


class SignalSamplingViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_uses_received_profile_for_rate_and_analysis(self):
        page = SignalPage()
        self.addCleanup(page.close)
        # Simulate queued data received before a connection changes its INFO.
        context = SimpleNamespace(config={"general": {"measurement": {"frequency_hz": 50}}},
                                  signal_page=page, service=SimpleNamespace(info=DeviceInfo(flags=2)))
        for samples in (32, 64):
            channels = [[math.sin(2 * math.pi * sample / samples) for sample in range(samples)] for _ in range(10)]
            MainWindow.on_signal(context, channels)
            capture = page.captures[-1]
            self.assertEqual(capture.samples_per_cycle, samples)
            self.assertEqual(capture.sample_rate_hz, samples * 50)
            self.assertEqual(len(page.moving_analysis), 1)
            self.assertAlmostEqual(page.analysis_result.channels["Ia"].fundamental.magnitude, 1 / math.sqrt(2), places=5)
            self.assertIn("0.00 to 20.00 ms", page.analysis_summary.state.text())

    def test_adc_time_axis_follows_info_profile(self):
        page = SignalPage()
        self.addCleanup(page.close)
        for flags, samples in ((2, 32), (0, 64)):
            context = SimpleNamespace(signal_page=page, service=SimpleNamespace(info=DeviceInfo(flags=flags)))
            channels = [[float(i) for i in range(samples * 2)] for _ in range(10)]
            MainWindow.on_adc(context, channels)
            self.assertEqual(page.adc_viewer.plots.current_wave.sample_rate_hz, samples * 50)
            self.assertEqual(page.adc_viewer.plots.voltage_wave.samples, channels[4:])
        page.adc_viewer.close()

    def test_fragmented_tcp_responses_reach_signal_and_adc_viewers(self):
        for flags, samples in ((3, 32), (1, 64)):
            with self.subTest(samples=samples):
                page, service = SignalPage(), DeviceService()
                service.info = DeviceInfo(flags=flags, connected=True)
                context = SimpleNamespace(config={}, signal_page=page, service=service)
                service.signal_received.connect(lambda channels: MainWindow.on_signal(context, channels))
                service.adc_received.connect(lambda channels: MainWindow.on_adc(context, channels))
                page.signal_requested.connect(service.request_signal)
                page.adc_requested.connect(service.request_adc)
                page.set_available(True)
                errors, requests = [], []
                service.message.connect(lambda message, level: errors.append(message) if level == "error" else None)
                listener = socket.socket()
                listener.settimeout(5)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                finish = threading.Event()
                signal_body = signal_payload(samples)
                if samples == 32:
                    signal_body += bytes(1280)

                def server():
                    try:
                        with listener.accept()[0] as connection:
                            connection.settimeout(5)

                            def exact(size):
                                body = b""
                                while len(body) < size:
                                    part = connection.recv(size - len(body))
                                    if not part:
                                        raise EOFError("Incomplete test request")
                                    body += part
                                return body

                            for body in (signal_body, adc_payload(samples, 2)):
                                header = exact(5)
                                size = struct.unpack_from("<H", header, 2)[0]
                                frame_type, request = beacheye.decode_native_frame(header + exact(size + 2))
                                requests.append(frame_type)
                                frame = beacheye.build_native_frame(frame_type, request[:1] + body)
                                for offset in range(0, len(frame), 137):
                                    connection.sendall(frame[offset:offset + 137])
                            finish.wait(5)
                    except BaseException as exc:
                        errors.append(str(exc))

                def wait_until(predicate):
                    deadline = time.monotonic() + 5
                    while not predicate() and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(0.005)
                    self.assertTrue(predicate(), errors)

                worker = threading.Thread(target=server, daemon=True)
                worker.start()
                try:
                    with patch.object(service, "_save_signal_diagnostic", return_value=""):
                        service._provider.start("127.0.0.1", listener.getsockname()[1])
                        page.get_button.click()
                        wait_until(lambda: len(page.captures) == 1)
                        self.assertEqual(page.plots.current_wave.samples[0], [i / samples for i in range(samples)])
                        page.adc_button.click()
                        wait_until(lambda: hasattr(page, "adc_viewer") and page.adc_viewer.isVisible())
                        self.assertEqual(page.adc_viewer.plots.current_wave.samples[3],
                                         [3000 + cycle * 100 + i for cycle in range(2) for i in range(samples)])
                        self.assertEqual(requests, [FRAME_SIGNAL, FRAME_ADC])
                        self.assertEqual(errors, [])
                finally:
                    finish.set()
                    service._provider.close()
                    listener.close()
                    worker.join(5)
                    page.close()

    def test_mixed_capture_history_keeps_cycle_windows_and_fault_origin(self):
        page = SignalPage()
        self.addCleanup(page.close)
        for samples in (32, 64):
            channels = [[math.sin(2 * math.pi * i / samples) for i in range(samples * 12)] for _ in range(10)]
            page.set_samples(channels, samples * 50, 50, samples_per_cycle=samples)
            self.assertEqual(page.captures[-1].cycle_count, 12)
            self.assertEqual(len(page.moving_analysis), 12)
        for index, samples in ((0, 32), (1, 64), (0, 32)):
            page._select_capture(index)
            self.assertEqual(page.plots.current_wave.time_origin_samples, -samples)
            self.assertIn("-20.00 to +0.00 ms", page._analysis_window_text(page.captures[index], page.moving_analysis[0]))
            page._select_cycle(2)
            self.assertEqual(page.moving_analysis[page.analysis_window_index].start_sample, 2 * samples)
            self.assertEqual(len(page.plots.current_wave.samples[0]), samples)
            page._show_analysis_details()
            self.assertIn(f"{samples} samples", page.analysis_window.window_description.text())
        page.analysis_window.close()


if __name__ == "__main__":
    unittest.main()
