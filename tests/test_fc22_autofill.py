"""Automatic form filling without a lot or a second board connection."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, PropertyMock
import unittest

from wolfeye.models import DeviceInfo, MeasurementSnapshot
from wolfeye.qt import QApplication, QSettings
from wolfeye.services.fc22_autofill import snapshot_readings
from wolfeye.services.fc22_session import Fc22SessionStore
from wolfeye.widgets.fc22_tester_page import Fc22TesterPage


class AutoFillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.page = Fc22TesterPage(Fc22SessionStore(Path(self.temp.name)))

    def tearDown(self):
        self.page.shutdown()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def connect_dut(self):
        self.page.set_device_info(DeviceInfo(model="FC22AR", build=51, firmware=17,
                                             connected=True, transport="Native TCP:6536"))

    def test_actual_values_fill_form_without_lot_and_persist_provenance(self):
        self.connect_dut()
        self.page.on_measurements(MeasurementSnapshot(
            analog={"Ua": 230, "Utr": 431, "Urs": 429, "Ia": 10, "F ABC": 5000, "Total PF": 98},
            binary={"AC supply": True, "Door open": False, "Lockout(Any)": False, "Open": True},
        ))
        self.assertEqual(self.page.session.test_data["va"], "230")
        self.assertEqual(self.page.session.test_data["vtr"], "431")
        self.assertEqual(self.page.session.test_data["vrs"], "429")
        self.assertEqual(self.page.session.test_data["freq_source"], "5000")
        self.assertEqual(self.page.session.test_data["door_true"], "False")
        self.assertNotIn("di_open", self.page.session.test_data)
        self.assertEqual(self.page.session.test_results, {})
        self.assertEqual(self.page.session.form_data["software_version"], "17")
        loaded = Fc22SessionStore(Path(self.temp.name)).load(self.page.session.session_id)
        self.assertEqual(loaded.auto_readings["va"]["source"], "analog.Ua")
        self.assertEqual(loaded.auto_readings["va"]["model"], "FC22AR")

    def test_missing_or_invalid_values_do_not_get_invented_or_keep_old_data(self):
        self.connect_dut()
        self.page.on_measurements(MeasurementSnapshot(analog={"Ua": 230}))
        self.page.on_measurements(MeasurementSnapshot(analog={"Ua": float("nan")}))
        self.assertNotIn("va", self.page.session.test_data)
        result = snapshot_readings(MeasurementSnapshot(analog={"Ia": True, "Battery Voltage": 27}, binary={"AC supply": 1}))
        self.assertEqual(result, {})

    def test_manual_edit_survives_timer_until_fresh_measurement(self):
        self.connect_dut()
        self.page.on_measurements(MeasurementSnapshot(analog={"Ua": 230}))
        self.page.section_list.setCurrentRow(0)
        self.page.test_fields["va"].setText("manual reading")
        self.page._lot_timer.timeout.emit()
        self.assertEqual(self.page.session.test_data["va"], "manual reading")
        self.assertNotIn("va", self.page.session.auto_readings)
        self.page.on_measurements(MeasurementSnapshot(analog={"Ua": 231}))
        self.assertEqual(self.page.session.test_data["va"], "231")

    def test_observations_expire_without_lot_and_clear_on_device_change(self):
        self.connect_dut()
        with patch("wolfeye.widgets.fc22_tester_page.time.monotonic", return_value=10):
            self.page.on_measurements(MeasurementSnapshot(analog={"Ua": 230}))
        with patch("wolfeye.widgets.fc22_tester_page.time.monotonic", return_value=41):
            self.page._lot_timer.timeout.emit()
        self.assertNotIn("va", self.page.session.test_data)
        self.page.on_measurements(MeasurementSnapshot(analog={"Ua": 230}))
        self.page.set_device_info(DeviceInfo(model="FC22S", connected=True, transport="Native TCP:6536"))
        self.assertNotIn("va", self.page.session.test_data)

    def test_new_session_adopts_existing_live_device(self):
        self.connect_dut()
        self.page._new_session()
        self.assertEqual(self.page.session.dut_model, "FC22AR")
        self.assertEqual(self.page.session.firmware, "17")
        self.page.on_measurements(MeasurementSnapshot(analog={"Ia": 10}))
        self.assertEqual(self.page.session.test_data["ia"], "10")

    def test_emwolf_feedback_is_recorded_without_lot_but_is_not_a_pass(self):
        self.connect_dut()
        self.page.on_emwolf_run_started("FC22AR")
        self.page.on_emwolf_result("FC22AR", {"scenario_1.trip_time_ms": 55, "scenario_1.completed": True})
        self.assertEqual(self.page.session.emwolf_results["scenario_1.trip_time_ms"], 55)
        self.assertNotIn("fault_phase_phase", self.page.session.test_data)
        self.assertIn("55 ms", self.page.emwolf_feedback.text())
        self.page.set_emwolf_board_state(False, "192.0.2.3", 666)
        self.page.on_emwolf_result("FC22AR", {"scenario_1.trip_time_ms": 99})
        self.assertEqual(self.page.session.emwolf_results["scenario_1.trip_time_ms"], 55)
        self.page.on_emwolf_run_started("FC22AR")
        self.assertEqual(self.page.session.emwolf_results, {})
        self.page._new_session()
        self.page.on_emwolf_result("FC22AR", {"scenario_1.trip_time_ms": 99})
        self.assertEqual(self.page.session.emwolf_results, {})

    def test_custom_acceptance_rule_owns_its_field_instead_of_default_mapping(self):
        self.connect_dut()
        self.page._activate_lot({"version": 1, "lot_id": "custom", "device_model": "FC22AR", "tests": [
            {"id": "voltage", "source": "external.reference_voltage", "report_field": "va",
             "filters": [{"type": "range", "min": 229, "max": 231}]}]})
        self.page.on_measurements(MeasurementSnapshot(analog={"Ua": 230, "Ib": 12}))
        self.assertNotIn("va", self.page.session.auto_readings)
        self.assertNotEqual(self.page.session.test_data.get("va"), "230")
        self.assertEqual(self.page.session.test_data["ib"], "12")

    def test_tester_controls_share_the_existing_emwolf_connection(self):
        from wolfeye.widgets.main_window import MainWindow
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        with patch("wolfeye.widgets.main_window.QSettings", return_value=settings), patch(
                "wolfeye.widgets.main_window.Fc22TesterPage", return_value=self.page):
            window = MainWindow()
        try:
            board = window.emwolf_page
            original_connection = board.connection
            self.page.emwolf_host.setText("192.0.2.3")
            self.page.emwolf_port.setValue(12345)
            with patch.object(board.connection, "connect") as connect:
                self.page.emwolf_connect_button.click()
                connect.assert_called_once_with("192.0.2.3", 12345)
            board._set_connection_state(True)
            self.assertTrue(self.page.emwolf_run_button.isEnabled())
            self.assertFalse(board.host.isEnabled())
            self.assertEqual(self.page.emwolf_connect_button.text(), "Disconnect EmWolf")
            with patch.object(board, "_commit", return_value=True), patch.object(board.connection, "send_project") as send:
                self.page.emwolf_run_button.click()
                send.assert_called_once_with(board.project)
            self.assertIs(board.connection, original_connection)
            with patch.object(type(window.service), "connected", new_callable=PropertyMock, return_value=True), patch.object(window.service, "refresh") as refresh:
                self.page.refresh_requested.emit()
                window._device_busy = True
                self.page.refresh_requested.emit()
                refresh.assert_called_once()
            self.page.emwolf_setup_requested.emit()
            self.assertIs(window.tabs.currentWidget(), window._tab_containers[board])
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
