"""WI03 rev 00 limits, setup contexts, review gates and worksheet integration."""
import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from wolfeye.models import DeviceInfo, MeasurementSnapshot
from wolfeye.qt import QApplication, QMessageBox
from wolfeye.services.fc22_instruction import load_instruction, native_readings, evaluate_case, validate_instruction
from wolfeye.services.fc22_session import Fc22SessionStore
from wolfeye.widgets.fc22_instruction_dialog import InstructionDialog
from wolfeye.widgets.fc22_tester_page import Fc22TesterPage


class InstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_instruction()
        cls.cases = {case["id"]: case for case in cls.catalog["cases"]}

    def result(self, case_id, check_id, value, unit, model="FC22AR", setup=True):
        return evaluate_case(self.cases[case_id], {check_id: {"value": value, "unit": unit}},
                             setup_confirmed=setup, model=model)[check_id]

    def test_source_identity_and_full_board_coverage(self):
        doc = self.catalog["document"]
        self.assertEqual((doc["code"],doc["revision"],doc["page_count"]), ("WI03","00",8))
        self.assertEqual(doc["sha256"], "4ced9b973ff12307a0390400b95566a721fb79bb32eeeb9e8b6019e2360daea0")
        self.assertEqual(len(self.cases), 38)
        self.assertEqual(sum(len(case["checks"]) for case in self.cases.values()), 104)
        self.assertEqual({case["board"] for case in self.cases.values()},
                         {"HMI","Keypad","Analog","Digital","Power","Base","Relay & key","Modem","AR DRV Power","LLDL"})

    def test_voltage_limits_match_both_word_tables(self):
        for model, mode, nominal in (("FC22AR","low",3.3),("FC22AR","high",7),("FC22S","low",3.2),("FC22S","high",3.9)):
            case = self.cases[f"{model.lower()}_voltage_{mode}"]
            self.assertEqual(case["checks"][0]["acceptance"], {"type":"tolerance","nominal":nominal,"absolute":.2})
            for value, status in ((nominal,"PASS"),(str(nominal+.3),"FAIL")):
                self.assertEqual(self.result(case["id"],"va",value,"kV",model)["status"],status)
            for row in case["checks"]:
                if row["id"].startswith("freq_"):
                    self.assertEqual(row["acceptance"], {"type":"tolerance","nominal":50,"absolute":.2})
                    self.assertNotIn("binding",row)
        self.assertEqual(self.result("fc22ar_voltage_low","va",3.1,"kV")["status"],"PASS")
        self.assertEqual(self.result("fc22ar_voltage_low","va",3.5,"kV")["status"],"PASS")

    def test_input_values_and_scope_limits_match_word(self):
        expected={"fc22s_voltage_low":(1.63,200,1.12),"fc22s_voltage_high":(2,100,1.24),
                  "fc22ar_voltage_low":(2.5,720,1.7),"fc22ar_voltage_high":(5.2,240,2.24)}
        for case_id,(stimulus,minimum,maximum) in expected.items():
            case=self.cases[case_id]
            rows={r["id"]:r for r in case["checks"]}
            self.assertEqual(case["inputs"][0]["acceptance"],{"type":"tolerance","nominal":stimulus,"absolute":.3})
            self.assertEqual(rows["scope_min"]["acceptance"],{"type":"tolerance","nominal":minimum,"absolute":50})
            self.assertEqual(rows["scope_max"]["acceptance"],{"type":"tolerance","nominal":maximum,"absolute":.4})

    def test_current_inputs_outputs_and_ambiguous_in_remain_exact(self):
        phase=self.cases["analog_phase_currents"]
        self.assertEqual(phase["inputs"][0]["acceptance"],{"type":"tolerance","nominal":200,"absolute":10})
        self.assertEqual(self.result("analog_phase_currents","ia",67,"A")["status"],"PASS")
        self.assertEqual(self.result("analog_phase_currents","ia",77,"A")["status"],"PASS")
        self.assertEqual(self.result("analog_neutral_current","in",170,"A")["status"],"PASS")
        self.assertEqual(self.result("analog_neutral_current","in",250,"A")["status"],"PASS")
        row=self.cases["analog_neutral_current"]["checks"][1]
        self.assertEqual(row["source_expression"],"2.7±3.3 V")
        self.assertEqual(row["acceptance"]["absolute"],3.3)
        self.assertEqual(self.result("analog_neutral_current","scope_difference",2.7,"V")["status"],"NOT_TESTED")

    def test_strict_power_boundaries_are_not_relaxed(self):
        for value,status in ((13,"FAIL"),(13.0001,"PASS")):
            self.assertEqual(self.result("power_ac","digital_vcc",value,"V")["status"],status)
        for value,status in ((11.4,"FAIL"),(11.6,"FAIL"),(11.5,"PASS")):
            self.assertEqual(self.result("power_ac","external_power",value,"V")["status"],status)

    def test_charger_and_battery_boundary_tolerances_require_review(self):
        for case_id,check,low,lt,high,ht in (("power_charger_on","charger_range",23.6,.1,24.2,.1),
                                           ("power_charger_off","charger_range",25,.2,26,.2),
                                           ("power_battery_voltage","battery_voltage",24,.1,26,.1)):
            row=self.cases[case_id]["checks"][0]
            rule=row["acceptance"]
            self.assertEqual((rule["lower"]["nominal"],rule["lower"]["absolute"],rule["upper"]["nominal"],rule["upper"]["absolute"]),(low,lt,high,ht))
            self.assertEqual(self.result(case_id,check,(low+high)/2,"V")["status"],"NOT_TESTED")

    def test_setup_model_and_units_are_required(self):
        self.assertEqual(self.result("fc22ar_voltage_low","va",3.3,"kV",setup=False)["status"],"NOT_TESTED")
        self.assertEqual(self.result("fc22ar_voltage_low","va",3.3,"kV",model="FC22S")["status"],"NOT_TESTED")
        self.assertEqual(self.result("fc22ar_voltage_low","va",3300,"V")["status"],"INVALID")
        self.assertEqual(self.result("fc22ar_voltage_low","va","NaN","kV")["status"],"INVALID")

    def test_native_conversions_use_existing_status_page_units(self):
        voltage=native_readings(self.cases["fc22ar_voltage_low"], MeasurementSnapshot(analog={"Ua":3300,"F ABC":5000}))
        self.assertEqual(voltage["va"]["value"],3.3)
        self.assertEqual(voltage["va"]["raw_value"],3300)
        self.assertNotIn("freq_source",voltage)
        currents=native_readings(self.cases["analog_phase_currents"],MeasurementSnapshot(analog={"Ia":720}))
        self.assertEqual(currents["ia"]["value"],72)

    def test_qualitative_checks_and_missing_limits_do_not_invent_timing(self):
        self.assertEqual(self.result("digital_ac","ac_supply",True,"boolean")["status"],"PASS")
        self.assertEqual(self.result("digital_ac","ac_supply",1,"boolean")["status"],"INVALID")
        self.assertEqual(self.result("modem_before_module","regulators",3.3,"V")["status"],"NOT_TESTED")
        self.assertNotIn("timeout",self.cases["digital_open"]["checks"][0]["acceptance"])

    def test_unsafe_or_invalid_schema_is_rejected(self):
        bad=copy.deepcopy(self.catalog)
        bad["cases"][0]["checks"][0]["acceptance"]={"type":"python","value":"exec()"}
        with self.assertRaises(ValueError):validate_instruction(bad)
        bad=copy.deepcopy(self.catalog)
        bad["cases"][0]["checks"][0]["binding"]={"source":"analog.Ua","unit":"A","multiplier":.1}
        with self.assertRaises(ValueError):validate_instruction(bad)


class InstructionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=TemporaryDirectory()
        self.page=Fc22TesterPage(Fc22SessionStore(Path(self.temp.name)))
        self.page.set_device_info(DeviceInfo(model="FC22AR",build=51,connected=True,transport="Native TCP:6536"))

    def tearDown(self):
        self.page.shutdown();self.page.close();self.page.deleteLater();self.app.processEvents();self.temp.cleanup()

    def dialog(self,case_id):
        case=next(c for c in self.page._instruction_catalog["cases"] if c["id"]==case_id)
        d=InstructionDialog(self.page._instruction_catalog,case,"FC22AR",self.page._instruction_current_snapshot,parent=self.page)
        self.addCleanup(d.close)
        return d

    def test_worksheet_live_values_manual_measurements_and_persistence(self):
        self.page.on_measurements(MeasurementSnapshot(analog={"Ia":720,"Ib":720,"Ic":720}))
        d=self.dialog("analog_phase_currents")
        self.assertEqual(d._evaluate()["ia"]["status"],"NOT_TESTED")
        d.confirm_setup.setChecked(True)
        d._controls["scope_difference"].setText("610")
        self.assertTrue(all(r["status"]=="PASS" for r in d._evaluate().values()))
        d._save();self.page._save_instruction_record(d.record)
        self.assertEqual(self.page.session.test_data["ia"],"72.0 A")
        self.page.on_measurements(MeasurementSnapshot(analog={"Ia":730}))
        self.assertEqual(self.page.session.test_data["ia"],"72.0 A")
        loaded=Fc22SessionStore(Path(self.temp.name)).load(self.page.session.session_id)
        record=loaded.instruction_results["analog_phase_currents"]
        self.assertEqual(record["results"]["ia"]["input_kind"],"device")
        self.assertEqual(record["results"]["scope_difference"]["input_kind"],"manual")
        self.assertTrue(self.page._instruction_complete())
        self.page.section_list.setCurrentRow(1)
        self.page.test_fields["ia"].setText("80 A")
        self.assertFalse(self.page._instruction_complete())

    def test_review_required_result_warns_before_pdf(self):
        self.page.on_measurements(MeasurementSnapshot(analog={"In":2100}))
        d=self.dialog("analog_neutral_current")
        d.confirm_setup.setChecked(True);d._controls["scope_difference"].setText("2.7")
        d._save();self.page._save_instruction_record(d.record)
        with patch("wolfeye.widgets.fc22_tester_page.QMessageBox.question",return_value=QMessageBox.StandardButton.No) as warning,patch("wolfeye.widgets.fc22_tester_page.fill_form") as pdf:
            self.page._generate_form();warning.assert_called_once();pdf.assert_not_called()

    def test_native_values_expire_in_worksheet_and_model_lists_follow_dut(self):
        self.page.on_measurements(MeasurementSnapshot(analog={"Ia":720}))
        d=self.dialog("analog_phase_currents");d.confirm_setup.setChecked(True)
        self.assertEqual(d._evaluate()["ia"]["status"],"PASS")
        self.page._instruction_received-=31
        d._update_native()
        self.assertEqual(d._evaluate()["ia"]["status"],"NOT_TESTED")
        self.page.set_device_info(DeviceInfo(model="FC22S",connected=True,transport="Native TCP:6536"))
        ids={self.page.instruction_case.itemData(i) for i in range(self.page.instruction_case.count())}
        self.assertIn("fc22s_voltage_low",ids)
        self.assertNotIn("fc22ar_voltage_low",ids)


if __name__=="__main__":unittest.main()
