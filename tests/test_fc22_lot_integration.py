"""Regressions at the real device, Qt, session and report boundaries."""
from __future__ import annotations

import json
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtTest import QTest
from wolfeye.qt import QApplication, QMessageBox
from wolfeye.models import DeviceInfo, MeasurementSnapshot
from wolfeye.services.beacheye import decode_measurements, settings_point_catalog
from wolfeye.services.fc22_session import Fc22SessionStore
from wolfeye.services.fc22_test_lot import TestLotEngine, known_points
from wolfeye.widgets.fc22_lot_editor import TestLotEditorDialog
from wolfeye.widgets.fc22_tester_page import Fc22TesterPage, RUN_TEST_SECTIONS


def lot(source="external.charging_voltage", field="charging_voltage", **extra):
    return {"version": 1, "lot_id": "integration", "device_model": "FC22S",
            "tests": [{"id": "reading", "source": source, "report_field": field,
                       "filters": [{"type": "range", "min": 25, "max": 30}], **extra}]}


class LotIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.page = Fc22TesterPage(Fc22SessionStore(Path(self.temp.name)))

    def tearDown(self):
        self.page.shutdown()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_company_measurements_work_for_both_models_and_revisions(self):
        for model in ("FC22AR", "FC22S"):
            for build in (50, 51, 52, 256):
                with self.subTest(model=model, build=build):
                    catalog = settings_point_catalog(model, build)
                    values = [50 if name == "F ABC" else 0 for _, name in catalog["analog"]]
                    payload = (struct.pack("<H", len(catalog["binary"]) << 4 | 1)
                               + bytes((len(catalog["binary"]) + 7) // 8)
                               + struct.pack("<H", len(values) << 4 | 2)
                               + struct.pack(f"<{len(values)}H", *values))
                    snapshot = decode_measurements(payload, model, build)
                    rules = lot("analog.F ABC", "freq_source")
                    rules["device_model"] = model
                    rules["tests"][0]["filters"] = [{"type": "range", "min": 49, "max": 51}]
                    result = TestLotEngine(rules).evaluate({"analog": snapshot.analog})
                    self.assertEqual(result["freq_source"].status, "PASS")
                    self.assertTrue(set(snapshot.analog) <= known_points(model)["analog"])
                    self.page._activate_lot(rules)
                    self.page.set_device_info(DeviceInfo(model=model, build=build, connected=True, transport="Native TCP:6536"))
                    self.page.on_measurements(snapshot)
                    self.assertEqual(self.page.session.test_results["freq_source"]["status"], "PASS")
                    self.page.set_device_info(DeviceInfo(connected=False))

    def test_editor_uses_company_sources_for_main_and_condition_fields(self):
        rules = lot("analog.F ABC", "freq_source")
        rules["tests"][0]["filters"].insert(0, {"type": "condition", "source": "binary.AC supply", "equals": True})
        editor = TestLotEditorDialog(rules, "FC22S", [("freq_source", "Frequency")], build=51)
        self.assertGreaterEqual(editor.test_source.findText("analog.F ABC"), 0)
        self.assertEqual(editor.test_source.findText("analog.Frequency"), -1)
        editor.model.setCurrentText("FC22AR")
        condition = editor._filter_rows[0].params["source"][0]
        self.assertGreaterEqual(condition.findText("analog.Isef"), 0)
        editor.close()
        editor.deleteLater()

    def test_manual_edit_keeps_incomplete_pdf_warning_and_waits_for_fresh_data(self):
        rules = lot("external.a", "freq_source")
        rules["tests"].append({"id": "b", "source": "external.b", "report_field": "freq_load",
                               "filters": [{"type": "range", "min": 25, "max": 30}]})
        self.page._activate_lot(rules)
        self.page.apply_external_test_values({"a": 27, "b": 40})
        index = next(i for i, s in enumerate(RUN_TEST_SECTIONS) if any(f.key == "freq_load" for f in s.fields))
        self.page.section_list.setCurrentRow(index)
        self.page.test_fields["freq_load"].setText("27")
        self.page._lot_timer.timeout.emit()
        self.assertEqual(self.page.session.test_results["freq_load"]["status"], "NOT_TESTED")
        self.assertEqual(self.page.session.test_data["freq_load"], "27")
        with patch("wolfeye.widgets.fc22_tester_page.QMessageBox.question", return_value=QMessageBox.StandardButton.No) as warning, patch("wolfeye.widgets.fc22_tester_page.fill_form") as pdf:
            self.page._generate_form()
            warning.assert_called_once()
            pdf.assert_not_called()
        self.page.apply_external_test_values({"b": 27})
        self.assertEqual(self.page.session.test_results["freq_load"]["status"], "PASS")

    def test_bench_model_switch_stops_listener_and_clears_verified_values(self):
        self.page._activate_lot(lot())
        self.page._bench_adapter.start(self.page.session.session_id, port=0)
        session_id, token = self.page.session.session_id, self.page._bench_adapter.token
        self.page._accept_bench_measurement(session_id, token, "charging_voltage", 27, "")
        self.assertEqual(self.page.session.test_results["charging_voltage"]["status"], "PASS")
        self.page.model_switch.setCurrentText("FC22AR")
        self.page._accept_bench_measurement(session_id, token, "charging_voltage", 27, "")
        self.assertFalse(self.page._bench_adapter.running)
        self.assertEqual(self.page.session.test_results["charging_voltage"]["status"], "NOT_TESTED")
        self.assertNotIn("charging_voltage", self.page.session.test_data)

    def test_old_tcp_frame_cannot_fill_new_session_after_qt_queue_delivery(self):
        self.page._activate_lot(lot())
        adapter = self.page._bench_adapter
        port = adapter.start(self.page.session.session_id, port=0)
        queued = threading.Event()
        emit = adapter._on_context_measurement
        def enqueue(*args):
            emit(*args)
            queued.set()
        adapter._on_context_measurement = enqueue
        previous_id = self.page.session.session_id
        message = {"version": 1, "session_id": previous_id, "token": adapter.token,
                   "source": "testbench", "type": "measurement", "device": "meter_1",
                   "sequence": 1, "field": "charging_voltage", "value": 27, "unit": ""}
        wire = json.dumps(message).encode()
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            client.sendall(struct.pack("!I", len(wire)) + wire)
            self.assertTrue(queued.wait(2))
        self.page._new_session()
        self.assertNotEqual(previous_id, self.page.session.session_id)
        self.page._activate_lot(lot())
        adapter.start(self.page.session.session_id, port=0)
        self.app.processEvents()
        self.assertNotIn("charging_voltage", self.page.session.test_data)
        self.assertNotEqual(self.page.session.test_results.get("charging_voltage", {}).get("status"), "PASS")

    def test_lot_change_rotates_bench_context(self):
        self.page._activate_lot(lot())
        self.page._bench_adapter.start(self.page.session.session_id, port=0)
        token = self.page._bench_adapter.token
        self.page._activate_lot(lot())
        self.page._bench_adapter.start(self.page.session.session_id, port=0)
        self.page._accept_bench_measurement(self.page.session.session_id, token, "charging_voltage", 27, "")
        self.assertNotIn("charging_voltage", self.page.session.test_data)

    def test_emwolf_timeout_fires_without_incoming_measurements(self):
        rules = lot("emwolf.scenario_1.trip_time_ms", "fault_phase_phase", unit="ms")
        rules["tests"][0]["filters"].append({"type": "timeout", "seconds": 0.01})
        self.page._activate_lot(rules)
        QTest.qWait(30)
        self.page._evaluate_lot({})
        self.assertEqual(self.page.session.test_results["fault_phase_phase"]["status"], "NOT_TESTED")
        self.page.on_emwolf_run_started("FC22S")
        QTest.qWait(350)
        self.assertEqual(self.page.session.test_results["fault_phase_phase"]["status"], "FAIL")

    def test_live_readings_expire_and_disconnect_clears_pass(self):
        rules = lot("analog.F ABC", "freq_source")
        rules["max_age_seconds"] = 0.05
        self.page._activate_lot(rules)
        self.page.set_device_info(DeviceInfo(model="FC22S", build=51, connected=True, transport="Native TCP:6536"))
        with patch("wolfeye.widgets.fc22_tester_page.time.monotonic", return_value=10):
            self.page.on_measurements(MeasurementSnapshot(analog={"F ABC": 27}))
        self.assertEqual(self.page.session.test_results["freq_source"]["status"], "PASS")
        with patch("wolfeye.widgets.fc22_tester_page.time.monotonic", return_value=11):
            self.page._lot_timer.timeout.emit()
        self.assertEqual(self.page.session.test_results["freq_source"]["status"], "NOT_TESTED")
        self.assertNotIn("freq_source", self.page.session.test_data)
        self.page.on_measurements(MeasurementSnapshot(analog={"F ABC": 27}))
        self.page.set_device_info(DeviceInfo(connected=False))
        self.assertEqual(self.page.session.test_results["freq_source"]["status"], "NOT_TESTED")

    def test_timer_does_not_count_repeated_value_as_fresh_stability_sample(self):
        rules = lot("analog.F ABC", "freq_source")
        rules["tests"][0]["filters"].append({"type": "stable", "samples": 2, "max_spread": 1})
        self.page._activate_lot(rules)
        self.page.set_device_info(DeviceInfo(model="FC22S", connected=True, transport="Native TCP:6536"))
        self.page.on_measurements(MeasurementSnapshot(analog={"F ABC": 27}))
        for _ in range(5):
            self.page._lot_timer.timeout.emit()
        self.assertEqual(self.page.session.test_results["freq_source"]["status"], "NOT_TESTED")
        self.page.on_measurements(MeasurementSnapshot(analog={"F ABC": 27}))
        self.assertEqual(self.page.session.test_results["freq_source"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
