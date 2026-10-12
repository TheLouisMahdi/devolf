"""Tests for measurement values rendered by the status page."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from wolfeye.qt import QApplication  # noqa: E402

from wolfeye.models import MeasurementSnapshot  # noqa: E402
from wolfeye.widgets.pages import (  # noqa: E402
    EventsPage,
    MeasurementPage,
    SignalPage,
    StatusPage,
)


class StatusPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_temperature_is_displayed_in_degrees_celsius(self) -> None:
        page = StatusPage()
        page.set_measurements(MeasurementSnapshot(analog={"Temperature": 270.0}))

        self.assertEqual(page.temperature.value_label.text(), "27.0 °C")

    def test_sectionalizer_uses_sectionalizing_status(self) -> None:
        page = StatusPage()
        page.set_device_model("FC22S")
        page.set_measurements(MeasurementSnapshot(binary={"CLP On": True}))

        self.assertEqual(page.summary_title_labels["AR"].text(), "Sectionalizing")
        self.assertEqual(page.summary_labels["AR"].text(), "● ON")

    def test_device_actions_follow_connection_availability(self) -> None:
        measurement = MeasurementPage()
        signal = SignalPage()
        events = EventsPage()

        self.assertFalse(measurement.refresh_button.isEnabled())
        self.assertFalse(signal.get_button.isEnabled())
        self.assertFalse(events.load_button.isEnabled())
        measurement.set_connected(True)
        signal.set_available(True)
        events.set_available(True)
        self.assertTrue(measurement.refresh_button.isEnabled())
        self.assertTrue(signal.get_button.isEnabled())
        self.assertTrue(events.load_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
