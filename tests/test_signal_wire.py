"""BeachEye v50 64-sample SIGNAL wire contract tests (no native DLL needed)."""

import ctypes as ct
import math
import struct
import unittest
from unittest.mock import patch

from wolfeye.services import wolfeye as beacheye
from wolfeye.services.signal_analysis import SignalAnalyzer


class SignalWireTests(unittest.TestCase):
    @staticmethod
    def payload(extra_channels=0):
        return struct.pack(
            "<" + "f" * ((10 + extra_channels) * 64),
            *(channel * 100 + sample / 64
              for channel in range(10 + extra_channels)
              for sample in range(64)),
        )

    @staticmethod
    def native_decode(name, payload, output, capacity, samples):
        assert name == "signal"
        assert samples == 64
        assert capacity == 640
        ct.memmove(output, payload, 640 * ct.sizeof(ct.c_float))
        return 640

    def test_64_samples_in_correct_channel_order(self):
        with patch.object(beacheye, "_decode", side_effect=self.native_decode):
            for extra_channels in (0, 2):
                with self.subTest(extra_channels=extra_channels):
                    decoded = beacheye.decode_signal(self.payload(extra_channels))
                    self.assertEqual(len(decoded), 10)
                    self.assertTrue(all(len(channel) == 64 for channel in decoded))
                    self.assertAlmostEqual(decoded[0][63], 63 / 64)
                    self.assertAlmostEqual(decoded[6][0], 600)
                    self.assertAlmostEqual(decoded[9][63], 900 + 63 / 64)

    def test_incorrect_lengths_rejected_before_native_call(self):
        with patch.object(beacheye, "_decode") as native:
            for length in (0, 1280, 2560 - 4, 2560 + 4, 3072 + 4):
                with self.subTest(length=length), self.assertRaises(ValueError):
                    beacheye.decode_signal(b"\0" * length)
            native.assert_not_called()

    def test_nan_and_infinite_samples_rejected(self):
        for nonfinite in (float("nan"), float("inf"), -float("inf")):
            values = bytearray(self.payload())
            struct.pack_into("<f", values, 256, nonfinite)
            with patch.object(beacheye, "_decode", side_effect=self.native_decode):
                with self.assertRaisesRegex(ValueError, "non-finite"):
                    beacheye.decode_signal(bytes(values))

    def test_genuine_finite_spikes_remain_visible(self):
        values = bytearray(self.payload())
        struct.pack_into("<f", values, (6 * 64 + 21) * 4, 10_000.0)
        with patch.object(beacheye, "_decode", side_effect=self.native_decode):
            self.assertEqual(beacheye.decode_signal(bytes(values))[6][21], 10_000.0)

    def test_analysis_uses_64_sample_nonoverlapping_windows(self):
        values = tuple(math.sin(2 * math.pi * i / 64) for i in range(128))
        windows = SignalAnalyzer().analyze_moving({"Ia": values}, 3200, 50)
        self.assertEqual([(w.start_sample, w.end_sample) for w in windows], [(0, 64), (64, 128)])


if __name__ == "__main__":
    unittest.main()
