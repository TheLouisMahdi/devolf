"""Regression tests for responsive layouts and guarded wheel input."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from wolfeye.qt import (  # noqa: E402
    QApplication,
    QGroupBox,
    QPoint,
    QPointF,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    Qt,
    QWheelEvent,
    QVBoxLayout,
    QWidget,
)

from wolfeye.styles import V2_COMPACT_STYLE, build_v2_style_sheet  # noqa: E402
from wolfeye.widgets.config_pages import GeneralPage  # noqa: E402
from wolfeye.widgets.main_window import _ValueControlWheelGuard  # noqa: E402


class ResponsiveUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _group(page: GeneralPage, title: str) -> QGroupBox:
        return next(group for group in page.findChildren(QGroupBox) if group.title() == title)

    def test_io_tables_fit_their_cells_and_scroll_as_one_page(self) -> None:
        page = GeneralPage()
        page.setStyleSheet(
            build_v2_style_sheet(CODE_ROOT / "assets") + V2_COMPACT_STYLE
        )
        page.resize(1250, 560)
        page.show()
        page.tabs.setCurrentIndex(4)
        self.app.processEvents()

        outputs = self._group(page, "Digital Outputs").findChild(QTableWidget)
        recognition = outputs.cellWidget(0, 3)
        pulse = outputs.cellWidget(0, 5)
        self.assertLessEqual(
            recognition.geometry().right(), outputs.viewport().rect().right()
        )
        self.assertLessEqual(pulse.geometry().right(), outputs.viewport().rect().right())

        indicators = self._group(page, "Indicators").findChild(QTableWidget)
        self.assertEqual(indicators.verticalScrollBar().maximum(), 0)
        page_scroll = page.tabs.currentWidget()
        self.assertIsInstance(page_scroll, QScrollArea)
        self.assertGreater(page_scroll.verticalScrollBar().maximum(), 0)
        page.hide()

    def test_wheel_changes_a_numeric_input_only_after_focus(self) -> None:
        guard = _ValueControlWheelGuard(self.app)
        self.app.installEventFilter(guard)
        try:
            scroll = QScrollArea()
            content = QWidget()
            layout = QVBoxLayout(content)
            spin = QSpinBox()
            spin.setRange(0, 10)
            spin.setValue(5)
            layout.addWidget(spin)
            layout.addStretch()
            content.setMinimumHeight(1000)
            scroll.setWidget(content)
            scroll.setWidgetResizable(True)
            scroll.resize(300, 200)
            scroll.show()
            self.app.processEvents()

            def send_wheel(delta: int) -> None:
                center = spin.rect().center()
                event = QWheelEvent(
                    QPointF(center),
                    QPointF(spin.mapToGlobal(center)),
                    QPoint(),
                    QPoint(0, delta),
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                    Qt.ScrollPhase.ScrollUpdate,
                    False,
                )
                QApplication.sendEvent(spin, event)
                self.app.processEvents()

            content.setFocus()
            send_wheel(-120)
            self.assertEqual(spin.value(), 5)
            self.assertGreater(scroll.verticalScrollBar().value(), 0)

            spin.setFocus()
            send_wheel(120)
            self.assertEqual(spin.value(), 6)
            scroll.hide()
        finally:
            self.app.removeEventFilter(guard)


if __name__ == "__main__":
    unittest.main()
