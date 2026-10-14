"""Hardware-free validation for JSON-driven FC22 acceptance rules."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wolfeye.services.fc22_test_lot import TestLotEngine, validate_lot, load_lot
from wolfeye.services.fc22_session import Fc22SessionStore


def test_case(source="analog.F ABC", field="freq_source", filters=None, **kwargs):
    return {
        "version": 1, "lot_id": "sample", "device_model": "FC22S",
        "tests": [{
            "id": "test1", "source": source, "report_field": field,
            "filters": filters or [{"type": "range", "min": 49.7, "max": 50.3}],
            **kwargs,
        }],
    }


class TestLotTests(unittest.TestCase):
    def test_range_boundaries_and_failures(self):
        engine = TestLotEngine(test_case())
        for number, status in [(49.7, "PASS"), (50.3, "PASS"), (49.69, "FAIL")]:
            self.assertEqual(engine.evaluate({"analog": {"F ABC": number}})["freq_source"].status, status)

    def test_missing_invalid_not_pass(self):
        engine = TestLotEngine(test_case())
        self.assertEqual(engine.evaluate({})["freq_source"].status, "NOT_TESTED")
        self.assertEqual(engine.evaluate({"analog": {"F ABC": "NaN"}})["freq_source"].status, "INVALID")

    def test_stability_collects_distinct_samples(self):
        spec = test_case(filters=[{"type": "stable", "samples": 3, "max_spread": 0.1}])
        engine = TestLotEngine(spec)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        statuses = [engine.evaluate({"analog": {"F ABC": x}}, start + timedelta(seconds=i))["freq_source"].status
                    for i, x in enumerate((50, 50.05, 50.04))]
        self.assertEqual(statuses, ["NOT_TESTED", "NOT_TESTED", "PASS"])
        self.assertEqual(engine.evaluate({"analog": {"F ABC": 49}}, start + timedelta(seconds=3))["freq_source"].status, "FAIL")

    def test_stability_needs_fresh_channel_samples(self):
        spec = test_case(filters=[{"type": "stable", "samples": 2, "max_spread": 0.2}])
        engine = TestLotEngine(spec)
        value = {"analog": {"F ABC": 50}}
        a = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(engine.evaluate(value, a, {"analog": 1})["freq_source"].status, "NOT_TESTED")
        self.assertEqual(engine.evaluate(value, a + timedelta(seconds=1), {"analog": 1})["freq_source"].status, "NOT_TESTED")
        self.assertEqual(engine.evaluate(value, a + timedelta(seconds=2), {"analog": 2})["freq_source"].status, "PASS")

    def test_stability_resets_after_failed_measurement(self):
        spec = test_case(filters=[
            {"type": "range", "min": 49, "max": 51},
            {"type": "stable", "samples": 2, "max_spread": 0.2},
        ])
        engine = TestLotEngine(spec)
        a = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(engine.evaluate({"analog": {"F ABC": 50}}, a)["freq_source"].status, "NOT_TESTED")
        self.assertEqual(engine.evaluate({"analog": {"F ABC": 52}}, a + timedelta(seconds=1))["freq_source"].status, "FAIL")
        self.assertEqual(engine.evaluate({"analog": {"F ABC": 50}}, a + timedelta(seconds=2))["freq_source"].status, "NOT_TESTED")

    def test_unknown_protocol_point_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown analog point"):
            validate_lot(test_case(source="analog.NO_SUCH_POINT"))

    def test_boolean_equals_not_numeric_equal(self):
        engine = TestLotEngine(test_case("binary.AC supply", "ac_available", [{"type": "equals", "value": True}]))
        self.assertEqual(engine.evaluate({"binary": {"AC supply": 1}})["ac_available"].status, "FAIL")
        self.assertEqual(engine.evaluate({"binary": {"AC supply": True}})["ac_available"].status, "PASS")

    def test_condition(self):
        filt = [{"type": "condition", "source": "binary.AC supply", "equals": True},
                {"type": "range", "min": 49.7, "max": 50.3}]
        engine = TestLotEngine(test_case(filters=filt))
        self.assertEqual(engine.evaluate({"analog": {"F ABC": 50}, "binary": {"AC supply": False}})["freq_source"].status, "NOT_TESTED")
        self.assertEqual(engine.evaluate({"analog": {"F ABC": 50}, "binary": {"AC supply": True}})["freq_source"].status, "PASS")

    def test_tolerance_percent(self):
        engine = TestLotEngine(test_case(filters=[{"type": "tolerance", "limit": 1, "mode": "percent"}], expected=50))
        self.assertEqual(engine.evaluate({"analog": {"F ABC": 50.5}})["freq_source"].status, "PASS")
        self.assertEqual(engine.evaluate({"analog": {"F ABC": 50.6}})["freq_source"].status, "FAIL")

    def test_transition(self):
        engine = TestLotEngine(test_case("binary.Open", "di_open", [{"type": "transition", "from": False, "to": True}]))
        self.assertEqual(engine.evaluate({"binary": {"Open": True}})["di_open"].status, "NOT_TESTED")
        self.assertEqual(engine.evaluate({"binary": {"Open": False}})["di_open"].status, "NOT_TESTED")
        self.assertEqual(engine.evaluate({"binary": {"Open": True}})["di_open"].status, "PASS")

    def test_timeout(self):
        engine = TestLotEngine(test_case(filters=[{"type": "equals", "value": 50}, {"type": "timeout", "seconds": 1}]))
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(engine.evaluate({}, start)["freq_source"].status, "NOT_TESTED")
        self.assertEqual(engine.evaluate({}, start + timedelta(seconds=2))["freq_source"].status, "FAIL")

    def test_late_valid_reply_remains_failure(self):
        engine = TestLotEngine(test_case(filters=[
            {"type": "equals", "value": 50}, {"type": "timeout", "seconds": 1}
        ]))
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(engine.evaluate({}, start)["freq_source"].status, "NOT_TESTED")
        self.assertEqual(engine.evaluate({"analog": {"F ABC": 50}}, start + timedelta(seconds=2))["freq_source"].status, "FAIL")

    def test_reject_invalid_rule(self):
        invalid = test_case(filters=[{"type": "shell", "command": "del C:\\"}])
        with self.assertRaises(ValueError):
            validate_lot(invalid)
        for test in (test_case(field="capacitor_series"),
                     test_case(filters=[{"type": "range", "min": 2, "max": 1}]),
                     test_case(filters=[{"type": "range", "min": "1", "max": 2}]),
                     test_case(filters=[{"type": "stable", "samples": 0, "max_spread": 1}])):
            with self.subTest(test=test), self.assertRaises(ValueError):
                validate_lot(test)

    def test_round_trip_session_with_rule_and_result(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            store = Fc22SessionStore(Path(tmp))
            store.new_session()
            lot = test_case()
            store.session.test_lot = lot
            store.session.test_results["freq_source"] = {"status": "FAIL", "value": 48.5, "reason": "outside accepted range"}
            store.session.auto_fields = ["freq_source"]
            store.save()
            loaded = store.load(store.session.session_id)
            self.assertEqual(loaded.test_lot, lot)
            self.assertEqual(loaded.test_results["freq_source"]["status"], "FAIL")
            self.assertEqual(loaded.auto_fields, ["freq_source"])

    def test_example_loads(self):
        from wolfeye.services.fc22_instruction import load_instruction
        instruction = load_instruction()
        self.assertEqual(instruction["document"]["code"], "WI03")
        self.assertTrue(instruction["cases"])


if __name__ == "__main__":
    unittest.main()
