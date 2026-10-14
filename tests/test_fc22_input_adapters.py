"""Hardware-free tests for EmWolf result mapping and bench TCP framing."""

import json
import socket
import struct
import threading
import time
import unittest
from types import SimpleNamespace

from wolfeye.services.fc22_input_adapters import (
    BenchTcpAdapter, emwolf_scenario_values, validate_bench_lot_source,
    validate_bench_message,
)
from wolfeye.services.fc22_test_lot import TestLotEngine, validate_lot


def lot():
    return {
        "version": 1, "lot_id": "bench-test", "device_model": "FC22S",
        "tests": [
            {"id": "charge", "source": "external.charging_voltage",
             "report_field": "charging_voltage", "unit": "V",
             "filters": [{"type": "range", "min": 25, "max": 30}]},
            {"id": "trip", "source": "emwolf.scenario_1.trip_time_ms",
             "report_field": "fault_phase_phase", "unit": "ms",
             "filters": [{"type": "range", "min": 10, "max": 100}]},
        ],
    }


class TestInputAdapters(unittest.TestCase):
    def test_bench_message_rejects_wrong_session_token_or_types(self):
        valid = {"version": 1, "source": "testbench", "type": "measurement", "device": "meter_1",
                 "sequence": 1, "session_id": "FC22-1", "token": "secret",
                 "field": "charging_voltage", "value": 26.4, "unit": "V"}
        self.assertEqual(validate_bench_message(valid, session_id="FC22-1", token="secret"),
                         ("meter_1", 1, "charging_voltage", 26.4, "V"))
        for update in ({"session_id": "wrong"}, {"token": "incorrect"}, {"version": True},
                       {"sequence": True}, {"value": []}, {"value": float("nan")},
                       {"field": "bad field"}, {"unit": 7}, {"source": "emwolf"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_bench_message({**valid, **update}, session_id="FC22-1", token="secret")

    def test_bench_lot_source_validates_field_and_unit(self):
        rules = validate_lot(lot())
        validate_bench_lot_source(rules, "charging_voltage", "V")
        for field, unit in (("charging_voltage", "mV"), ("unknown", "V")):
            with self.assertRaises(ValueError):
                validate_bench_lot_source(rules, field, unit)

    def test_emwolf_needs_confirmed_trip_and_applies_lot_rules(self):
        execution = SimpleNamespace(trip_time_us=55000, trip_input=2,
                                    trip_value=True, operation="TRIP")
        data = emwolf_scenario_values(0, execution)
        self.assertEqual(data["scenario_1.trip_time_ms"], 55)
        self.assertTrue(data["scenario_1.completed"])
        engine = TestLotEngine(lot())
        self.assertEqual(engine.evaluate({"emwolf": data})["fault_phase_phase"].status, "PASS")
        self.assertEqual(engine.evaluate({"emwolf": {"scenario_1.trip_time_ms": 110}})
                         ["fault_phase_phase"].status, "FAIL")
        with self.assertRaises(ValueError):
            emwolf_scenario_values(0, SimpleNamespace(trip_time_us=None, trip_input=2, trip_value=True))

    def test_bench_tcp_fragmented_and_duplicate_sequence(self):
        received, errors = [], []
        adapter = BenchTcpAdapter(lambda field, value, unit: received.append((field, value, unit)),
                                  errors.append)
        port = adapter.start("FC22-test", port=0)
        try:
            message = {"version": 1, "session_id": "FC22-test", "token": adapter.token,
                       "source": "testbench", "type": "measurement", "device": "meter_1",
                       "sequence": 1, "field": "charging_voltage", "value": 26.2, "unit": "V"}
            wire = json.dumps(message).encode()
            frame = struct.pack("!I", len(wire)) + wire
            with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                connection.sendall(frame[:2])
                connection.sendall(frame[2:11])
                connection.sendall(frame[11:])
                connection.sendall(frame)
            for _ in range(100):
                if errors:
                    break
                time.sleep(.01)
            self.assertEqual(received, [("charging_voltage", 26.2, "V")])
            self.assertTrue(any("duplicate" in message for message in errors))
        finally:
            adapter.stop()
        self.assertFalse(adapter.running)

    def test_bench_tcp_rejects_oversized_and_bad_json(self):
        errors = []
        adapter = BenchTcpAdapter(lambda *args: self.fail("invalid data accepted"), errors.append)
        port = adapter.start("FC22-test", port=0)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                connection.sendall(struct.pack("!I", 9000))
            with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                connection.sendall(struct.pack("!I", 2) + b"{}")
            for _ in range(100):
                if len(errors) >= 2:
                    break
                time.sleep(.01)
            self.assertEqual(len(errors), 2)
        finally:
            adapter.stop()


class TestChannelReset(unittest.TestCase):
    def test_new_emwolf_run_retains_independent_bench_history(self):
        specification = lot()
        engine = TestLotEngine(specification)
        initial = {"external": {"charging_voltage": 27},
                   "emwolf": {"scenario_1.trip_time_ms": 42}}
        self.assertEqual(engine.evaluate(initial)["charging_voltage"].status, "PASS")
        self.assertEqual(engine.evaluate(initial)["fault_phase_phase"].status, "PASS")
        engine.reset_channel("emwolf")
        result = engine.evaluate({"external": {"charging_voltage": 27}})
        self.assertEqual(result["charging_voltage"].status, "PASS")
        self.assertEqual(result["fault_phase_phase"].status, "NOT_TESTED")


if __name__ == "__main__":
    unittest.main()
