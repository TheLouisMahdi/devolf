"""Golden outputs from WolfEye master, without loading WolfEye's old DLL."""
import hashlib
import json
import random
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wolfeye.services.wolfeye import cycle_ar_stage, calculate_tcc_trip_ms
from wolfeye.widgets.main_window import MainWindow


class WolfEyePythonTests(unittest.TestCase):
    def test_signal_request_does_not_depend_on_settings_editors(self):
        context = SimpleNamespace(service=SimpleNamespace(request_signal=Mock()),
                                  _collect_config=Mock(side_effect=ValueError("invalid pending edit")))
        MainWindow.request_signal(context)
        context.service.request_signal.assert_called_once_with()
        context._collect_config.assert_not_called()

    def test_ar_matches_12000_company_cpp_transitions(self):
        # Golden SHA from the pinned company's unchanged C++ stage functions.
        rng, outputs = random.Random(32), []
        with patch("ctypes.CDLL", side_effect=OSError("no WolfEye DLL")):
            for i in range(12000):
                sef = i % 2 == 0
                count = 4 if sef else 12
                modes = [rng.randrange(4) for _ in range(count)]
                disabled = [bool(rng.randrange(2)) for _ in range(count)]
                row = 0 if sef else rng.randrange(3)
                stage = rng.randrange(4)
                outputs.append(cycle_ar_stage(modes, disabled, row, stage, sef))
        self.assertEqual(hashlib.sha256(json.dumps(outputs).encode()).hexdigest(),
                         "89f35456b46d48da8d9baaa1f1dec922baaa65e0ad35f45b886afa04f34b4c55")

    def test_tcc_matches_6000_company_cpp_times(self):
        rng, outputs = random.Random(64), []
        with patch("ctypes.CDLL", side_effect=OSError("no WolfEye DLL")):
            for i in range(6000):
                typ = i % 13
                pickup = rng.randint(1, 1000)
                current = rng.randint(pickup, 65535)
                tm = rng.uniform(.01, 10)
                minimum = rng.randrange(1000)
                maximum = rng.randrange(1000, 500000)
                adder = rng.randrange(1000)
                td = rng.randrange(20000)
                outputs.append(calculate_tcc_trip_ms(typ, pickup, tm, minimum, maximum, adder, td, current))
        self.assertEqual(hashlib.sha256(json.dumps(outputs).encode()).hexdigest(),
                         "d402a81eceb262ceeaa188ac2658449b054a4e1b846fa01c4b963528333955ec")

    def test_invalid_tcc_and_ar_are_rejected(self):
        self.assertIsNone(calculate_tcc_trip_ms(13, 100, 1, 0, 1000, 0, 0, 200))
        self.assertIsNone(calculate_tcc_trip_ms(1, 100, float("nan"), 0, 1000, 0, 0, 200))
        self.assertEqual(calculate_tcc_trip_ms(1, 100, 1, 0, 1000, 0, 0, 100), 1000)
        with self.assertRaises(ValueError):
            cycle_ar_stage([0] * 12, [False] * 12, 3, 0, False)
