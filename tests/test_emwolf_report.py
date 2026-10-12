import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from wolfeye.services.emwolf_protocol import (
    AnalogOutput,
    DeviceMetadata,
    Project,
    Scenario,
    Setup,
)
from wolfeye.services.emwolf_report import (
    EmWolfRunReport,
    _end_condition,
    generate_emwolf_pdf,
)


class EmWolfReportTests(unittest.TestCase):
    def _project(self) -> Project:
        timed = Scenario(name="Pre-fault", end_type="TIME", end_value=0.25)
        trip = Scenario(
            name="Feeder trip",
            end_type="DI_TOGGLE",
            digital_input=1,
            digital_outputs=[True, False, False, False],
        )
        trip.analogs["Va"] = AnalogOutput(
            enabled=True, amplitude=57.7, frequency=50.0, phase=0
        )
        return Project(
            setup=Setup(
                sample_time_us=8.2,
                digital_input_names=["OPEN & TRIP", "CLOSE", "AUX", "BLOCK"],
            ),
            scenarios=[timed, trip],
            device=DeviceMetadata(
                model="FC22AR",
                ip="192.0.2.10",
                firmware=3,
                hardware=2,
                build=50,
                transport="Native TCP:6536",
            ),
        )

    def test_end_condition_uses_the_configured_input_name(self) -> None:
        project = self._project()

        self.assertEqual(
            _end_condition(project.scenarios[1], project.setup),
            "OPEN & TRIP (DI1) - toggle",
        )

    def test_board_result_is_trip_time_not_raw_di_event_timestamp(self) -> None:
        report = EmWolfRunReport.begin(
            self._project(), started_at=datetime(2026, 9, 23, tzinfo=timezone.utc)
        )

        report.record_transition(1, True, 120_548_480)
        scenario_index = report.record_trip(1, False, 18_170)

        self.assertEqual(scenario_index, 1)
        self.assertEqual(report.executions[0].state, "CONFIGURED")
        self.assertEqual(report.executions[1].state, "TRIPPED")
        self.assertEqual(report.executions[1].trip_time_us, 18_170)
        self.assertEqual(report.executions[1].trip_value, False)
        self.assertEqual(
            [(item.value, item.elapsed_us) for item in report.executions[1].transitions],
            [(True, 120_548_480)],
        )

    def test_di_events_remain_history_until_board_result_arrives(self) -> None:
        report = EmWolfRunReport.begin(self._project())

        self.assertIsNone(report.record_transition(2, True, 3_000))
        self.assertEqual(report.record_transition(1, False, 4_250), 1)
        self.assertIsNone(report.record_transition(1, True, 4_500))
        report.record_trip(1, False, 4_900)

        self.assertEqual(report.executions[1].trip_time_us, 4_900)
        self.assertEqual(report.executions[1].trip_input, 1)
        self.assertEqual(len(report.executions[1].transitions), 1)

    def test_result_is_fallback_when_no_di_event_was_received(self) -> None:
        report = EmWolfRunReport.begin(self._project())

        report.record_trip(1, False, 18_170)

        self.assertEqual(report.executions[1].trip_time_us, 18_170)

    def test_open_then_close_is_reported_as_reclose(self) -> None:
        project = self._project()
        project.scenarios.append(
            Scenario(name="Dead time", end_type="DI_TOGGLE", digital_input=2)
        )
        report = EmWolfRunReport.begin(project)

        self.assertEqual(report.record_trip(1, False, 18_170), 1)
        self.assertEqual(report.executions[1].operation, "TRIP")
        self.assertIsNone(report.record_trip(1, True, 20_000))
        self.assertEqual(report.record_trip(2, True, 350_000), 2)
        self.assertEqual(report.executions[2].operation, "RECLOSE")
        self.assertEqual(report.executions[2].state, "RECLOSED")

    def test_sectionalizer_close_is_not_reported_as_reclose(self) -> None:
        project = Project(
            setup=Setup(
                digital_input_names=["Input 1", "Input 2", "DI3", "DI4"]
            ),
            scenarios=[
                Scenario(name="Fault", end_type="DI_TOGGLE", digital_input=2),
                Scenario(name="Close check", end_type="DI_TOGGLE", digital_input=1),
            ],
            device=DeviceMetadata(model="FC22S"),
        )
        report = EmWolfRunReport.begin(project)

        report.record_trip(2, True, 12_000)
        report.record_trip(1, True, 2_000_000)

        self.assertEqual(report.executions[0].operation, "TRIP")
        self.assertEqual(report.executions[1].operation, "CLOSE")
        self.assertEqual(report.executions[1].state, "CLOSED")

    def test_pdf_report_is_created(self) -> None:
        report = EmWolfRunReport.begin(self._project())
        report.record_transition(1, True, 13_775)
        report.record_trip(1, False, 18_170)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.pdf"
            generate_emwolf_pdf(output, report)
            content = output.read_bytes()

        self.assertTrue(content.startswith(b"%PDF-"))
        self.assertGreater(len(content), 10_000)


if __name__ == "__main__":
    unittest.main()
