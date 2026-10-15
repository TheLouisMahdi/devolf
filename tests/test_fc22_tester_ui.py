"""FC22 layout and provenance across navigation and manual edits."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path

from wolfeye.qt import QApplication, QFont, QFontDatabase, QScrollArea
from wolfeye.services.fc22_session import Fc22SessionStore
from wolfeye.widgets.fc22_tester_page import Fc22TesterPage


class TesterLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not QFontDatabase.families() and Path("C:/Windows/Fonts/segoeui.ttf").exists():
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        cls.app.setFont(QFont("Segoe UI", 9))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.page = Fc22TesterPage(Fc22SessionStore(Path(self.temp.name)))

    def tearDown(self):
        self.page.shutdown()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_navigation_and_actions_fit_small_and_large_windows(self):
        self.page.show()
        for width, height in ((900, 600), (1280, 760)):
            self.page.resize(width, height)
            for step in range(4):
                self.page._show_step(step)
                self.app.processEvents()
                for scroll in self.page.step_pages[step].findChildren(QScrollArea):
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                for button in self.page.step_buttons:
                    self.assertTrue(self.page.rect().contains(button.geometry().bottomRight()))
            self.page._show_step(2)
            self.app.processEvents()
            position = self.page.next_button.mapTo(self.page, self.page.next_button.rect().bottomRight())
            self.assertTrue(self.page.rect().contains(position))
            self.assertEqual(self.page.test_table.horizontalScrollBar().maximum(), 0)

    def test_verdict_and_source_follow_fresh_data_and_manual_override(self):
        self.page._activate_lot({"version": 1, "lot_id": "ui", "device_model": "FC22AR",
            "tests": [{"id": "voltage", "source": "external.va", "report_field": "va",
                       "expected": 100, "filters": [{"type": "tolerance", "mode": "percent", "limit": 2}]}]})
        self.page._show_step(2)
        self.page.apply_external_test_values({"va": 103})
        self.assertEqual(self.page.test_table.item(0, 3).text(), "FAIL")
        self.assertIn('"mode": "percent"', self.page.test_table.item(0, 0).toolTip())
        self.page.test_fields["va"].setText("100")
        self.assertEqual(self.page.test_table.item(0, 3).text(), "PENDING")
        self.page.section_list.setCurrentRow(1)
        self.page.section_list.setCurrentRow(0)
        self.assertEqual(self.page.test_fields["va"].text(), "100")
        self.page.apply_external_test_values({"va": 100})
        self.assertEqual(self.page.test_table.item(0, 3).text(), "PASS")

    def test_pdf_actions_require_a_generated_file(self):
        self.assertFalse(self.page.open_button.isEnabled())
        self.assertFalse(self.page.print_button.isEnabled())
        pdf = Path(self.temp.name) / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        self.page.current_pdf = pdf
        self.page._refresh_report_file()
        self.assertTrue(self.page.open_button.isEnabled())
        self.page._new_session()
        self.assertFalse(self.page.open_button.isEnabled())
        self.assertEqual(self.page.session_combo.currentText(), self.page.session.session_id)
