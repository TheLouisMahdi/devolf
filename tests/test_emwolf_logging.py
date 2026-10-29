"""User-facing logs retain indexed scenario/DI events without replay noise."""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from dataclasses import asdict
from wolfeye.qt import QApplication
from wolfeye.services.emwolf_protocol import Project, Scenario
from wolfeye.widgets.emwolf_page import EmWolfPage

class EmWolfLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.page=EmWolfPage()
        self.project=Project(scenarios=[Scenario(name="SHOT_1",end_type="DI_TOGGLE",digital_input=1)])
        self.project.device.model="FC22AR"
        self.restore(123)

    def tearDown(self):
        self.page.close()

    def restore(self,run_id):
        self.page._handle_run_state(dict(restore=dict(id=run_id,project=asdict(self.project),
            started_at="2026-10-25T11:00:00+03:30",state=2,collected=False)))

    def events(self):
        for sequence,kind,us in [(1,1,100),(2,2,101),(3,3,17101),(4,4,17101),(5,5,17101)]:
            self.page._handle_run_event(dict(sequence=sequence,kind=kind,scenario=0,
                input_id=1 if kind in (3,4) else 0,value=kind in (3,4),time_us=us))

    def lines(self):
        return [line.split("  ",1)[1] for line in self.page.log_view.toPlainText().splitlines()]

    def test_actual_output_start_di_once_and_end(self):
        self.events()
        self.assertEqual(self.lines(),["SHOT_1 start","DI1 17.101 ms","SHOT_1 end"])
        self.assertEqual(self.page.execution_report.executions[0].trip_time_us,17101)

    def test_reconnect_rebuilds_report_without_repeating_cleared_history(self):
        self.events();self.page.clear_log();self.restore(123);self.events()
        self.assertEqual(self.lines(),[])
        self.assertEqual(self.page.execution_report.executions[0].trip_time_us,17101)
        self.restore(456);self.events()
        self.assertEqual(self.lines(),["SHOT_1 start","DI1 17.101 ms","SHOT_1 end"])

    def test_connection_progress_hidden_errors_and_named_upload_retained(self):
        for text in ["Connecting to 127.0.0.1:666...","Connected","Disconnected",
                     "All 5 EmWolf events are durably received; board receipt confirmed","Loaded project.json"]:
            self.page._connection_log(text)
        self.assertEqual(self.lines(),[])
        self.page._connection_log("Connected scenario sent")
        self.page._connection_log("Connection error: peer reset")
        self.assertEqual(self.lines(),["Connected scenario sent","Connection error: peer reset"])
