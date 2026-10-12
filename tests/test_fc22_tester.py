"""FC22 Tester integration tests (session, form PDF, page wiring)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from wolfeye.qt import QApplication  # noqa: E402

from wolfeye.models import DeviceInfo  # noqa: E402
from wolfeye.services.fc22_form_pdf import fill_form  # noqa: E402
from wolfeye.services.fc22_session import Fc22SessionStore  # noqa: E402
from wolfeye.widgets.fc22_tester_page import (  # noqa: E402
    RUN_TEST_FIELD_KEYS,
    Fc22TesterPage,
)


def _entered_form_values() -> dict[str, object]:
    return {
        "product_type": "Recloser Control",
        "panel_sn": "PNL-77",
        "cubicle_sn": "CUB-77",
        "relay_sn": "RLY-77",
        "cable_bundling": "OK",
        "socket_sn": "SOC-77",
        "modem_type": "C3243",
        "modem_data_port": "1",
        "modem_id": "MDM-01",
        "modem_sn": "MDM-77",
        "appearance": "Accepted",
        "transformer_sn": "TR-77",
        "battery_kind": "VRLA",
        "mfg_date": "2026-08",
        "main_socket": "OK",
        "power_socket": "OK",
        "software_version": "17",
    }


def _entered_test_values() -> dict[str, object]:
    values: dict[str, object] = {key: "1.0" for key in RUN_TEST_FIELD_KEYS}
    values.update(
        {
            "do_trip": "PASS",
            "do_close": "PASS",
            "do_battery": "FAIL",
            "do_heater": "UNKNOWN",
            "di_open": "PASS",
            "di_close": "PASS",
            "di_lock": "PASS",
            "di_gas": "PASS",
            "modem_status": "PASS",
            "sim_card": "PASS",
            "ip_acquisition": "UNKNOWN",
            "fault_phase_phase": "PASS",
            "fault_phase_ground": "PASS",
            "fault_phase_sync": "PASS",
            "reclose_4_shot": "PASS",
            "dcd": "PASS",
            "inner_lamp": "PASS",
            "live_line": "PASS",
            "dead_line": "PASS",
            "led_indicators": "PASS",
            "ac_available": "True",
            "door_true": "True",
            "lockout_true": "False",
            "external_modem": "UNKNOWN",
        }
    )
    return values


class SessionTests(unittest.TestCase):
    def test_session_round_trip_persists_form_and_test_values(self) -> None:
        root = Path(tempfile.mkdtemp())
        store = Fc22SessionStore(root)
        session = store.new_session()
        session.operator = "op1"
        session.work_order = "WO-1"
        session.dut_model = "FC22AR"
        session.firmware = "17"
        session.form_data = dict(_entered_form_values())  # type: ignore[arg-type]
        session.test_data = dict(_entered_test_values())
        store.save()

        reloaded = Fc22SessionStore(root).load(session.session_id)
        self.assertEqual(reloaded.operator, "op1")
        self.assertEqual(reloaded.form_data["panel_sn"], "PNL-77")
        self.assertEqual(reloaded.test_data["do_battery"], "FAIL")
        self.assertEqual(reloaded.test_data["lockout_true"], "False")
        self.assertEqual(reloaded.firmware, "17")

    def test_new_session_is_listed_in_history(self) -> None:
        root = Path(tempfile.mkdtemp())
        store = Fc22SessionStore(root)
        session = store.new_session()
        self.assertIn(session.session_id, store.list_sessions())


class FormPdfTests(unittest.TestCase):
    def test_generated_pdf_contains_entered_values(self) -> None:
        output = Path(tempfile.mkdtemp()) / "final_inspection_S.pdf"
        data: dict[str, object] = dict(_entered_form_values())
        data.update(_entered_test_values())
        data["test_date"] = "2026-09-28"
        fill_form("s", output, data=data)
        self.assertTrue(output.exists())

        with fitz.open(output) as doc:
            text = doc[0].get_text()
        for expected in (
            "PNL-77",
            "CUB-77",
            "RLY-77",
            "SOC-77",
            "TR-77",
            "MDM-77",
            "2026-09-28",
            "PASS",
            "FAIL",
        ):
            self.assertIn(expected, text)
        # Result selectors must be rendered as chosen, not replaced by demo data.
        self.assertNotIn("DEMO OUTPUT", text)


class TesterPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _page(self) -> Fc22TesterPage:
        return Fc22TesterPage(Fc22SessionStore(Path(tempfile.mkdtemp())))

    def test_page_builds_with_four_workflow_steps(self) -> None:
        page = self._page()
        self.assertEqual(len(page.step_pages), 4)
        self.assertEqual(len(page.step_buttons), 4)
        self.assertIsNotNone(page.session)
        page.shutdown()

    def test_workflow_buttons_show_the_selected_step(self) -> None:
        page = self._page()
        page.show()
        self.app.processEvents()

        page.step_buttons[1].click()
        self.app.processEvents()

        self.assertTrue(page.step_pages[1].isVisible())
        self.assertFalse(page.step_pages[0].isVisible())
        page.shutdown()

    def test_device_info_fills_software_version_from_lan_identity(self) -> None:
        page = self._page()
        info = DeviceInfo(
            ip="192.168.137.10",
            model="FC22AR",
            firmware=17,
            hardware=3,
            build=51,
            connected=True,
            transport="Native TCP:6536",
        )
        page.set_device_info(info)
        self.assertEqual(page.session.firmware, "17")
        self.assertEqual(page.session.dut_model, "FC22AR")
        # Software Version form field is auto-filled, never typed.
        self.assertEqual(page.fields["software_version"].text(), "17")
        page.shutdown()

    def test_run_test_values_persist_through_navigation(self) -> None:
        page = self._page()
        page._show_step(2)
        page._show_section(5)  # Digital Outputs
        page.test_fields["do_trip"].setCurrentText("PASS")
        page.test_fields["do_battery"].setCurrentText("FAIL")
        page._show_section(0)  # navigate away (saves)
        page._show_section(5)  # navigate back
        self.assertEqual(page.test_fields["do_trip"].currentData(), "PASS")
        self.assertEqual(page.test_fields["do_battery"].currentData(), "FAIL")
        self.assertEqual(page.session.test_data["do_trip"], "PASS")
        page.shutdown()

    def test_generated_report_uses_session_values(self) -> None:
        page = self._page()
        page.session.form_data = dict(_entered_form_values())  # type: ignore[arg-type]
        page.session.test_data = dict(_entered_test_values())
        page.session.dut_model = "FC22AR"
        page._show_step(3)
        page._generate_form()
        self.assertIsNotNone(page.current_pdf)
        self.assertTrue(page.current_pdf.exists())
        page.shutdown()


if __name__ == "__main__":
    unittest.main()
