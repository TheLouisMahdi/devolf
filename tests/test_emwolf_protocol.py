import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wolfeye.services.emwolf_protocol import (
    DIEventDebouncer,
    EmWolfConnection,
    EW_START,
    EW_STOP,
    EW_STOP_TOKEN,
    AnalogOutput,
    DeviceMetadata,
    FrameDecoder,
    Project,
    Scenario,
    Setup,
    crc_ccitt,
    decode_di_event,
    decode_result,
    emwolf_default_scenario,
    load_project,
    save_project,
)


class EmWolfProtocolTests(unittest.TestCase):
    def test_crc_matches_ccitt_false_reference(self) -> None:
        self.assertEqual(crc_ccitt(b"123456789"), 0x29B1)

    def test_project_round_trips_through_frame_decoder(self) -> None:
        scenario = Scenario()
        scenario.analogs["Va"] = AnalogOutput(
            enabled=True,
            amplitude=1.5,
            frequency=50.0,
            phase=120,
            harmonic1_order=7,
            harmonic1_amplitude=0.2,
        )
        scenario.digital_outputs = [True, False, False, True]
        scenario.end_type = "DI_TOGGLE"
        scenario.digital_input = 2
        project = Project(setup=Setup(sample_time_us=20.0), scenarios=[scenario])

        payload = project.build_payload()
        self.assertEqual(len(payload), 197)
        self.assertEqual(payload[20:24], b"EWS2")
        self.assertEqual(struct.unpack_from("<H", payload, 24)[0], 1)
        self.assertEqual(payload[186], 0x09)
        self.assertEqual(payload[187], 0x00)
        self.assertEqual(list(FrameDecoder().feed(project.build_frame())), [(EW_START, payload)])

    def test_legacy_falling_edge_is_loaded_as_toggle(self) -> None:
        scenario = Scenario.from_dict({"end_type": "DI_FALLING", "digital_input": 1})
        payload = Project(scenarios=[scenario]).build_payload()

        self.assertEqual(scenario.end_type, "DI_TOGGLE")
        self.assertEqual(len(payload), 197)
        self.assertEqual(payload[20:24], b"EWS2")
        self.assertEqual(payload[187], 0x00)

    def test_digital_input_names_round_trip_without_changing_wire_format(self) -> None:
        setup = Setup(digital_input_names=["OPEN", "CLOSE", "AUX", "BLOCK"])
        project = Project(
            setup=setup,
            scenarios=[Scenario(end_type="DI_TOGGLE", digital_input=1)],
            device=DeviceMetadata(
                model="FC22AR",
                ip="192.0.2.10",
                firmware=3,
                hardware=2,
                build=50,
                transport="Native TCP:6536",
            ),
        )

        payload = project.build_payload()
        self.assertEqual(len(payload), 197)
        self.assertEqual(project.setup.digital_input_name(1), "OPEN")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "named-inputs.json"
            save_project(path, project)
            loaded = load_project(path)

        self.assertEqual(
            loaded.setup.digital_input_names,
            ["OPEN", "CLOSE", "AUX", "BLOCK"],
        )
        self.assertEqual(loaded.device.model, "FC22AR")
        self.assertEqual(loaded.device.build, 50)
        self.assertEqual(loaded.build_payload(), payload)

    def test_legacy_project_gets_default_digital_input_names(self) -> None:
        project = Project.from_dict({"setup": {}, "scenarios": [{}]})

        self.assertEqual(project.setup.digital_input_names, ["DI1", "DI2", "DI3", "DI4"])

    def test_default_scenario_contains_expected_three_phase_values(self) -> None:
        scenario = emwolf_default_scenario()
        self.assertEqual(scenario.end_type, "INFINITE")
        self.assertEqual(scenario.analogs["Va"].amplitude, 1.0)
        self.assertEqual(scenario.analogs["Vc"].phase, 240)
        self.assertEqual(scenario.analogs["Ib"].amplitude, 0.3)
        self.assertTrue(all(item.enabled for item in scenario.analogs.values()))

    def test_current_limit_includes_fundamental_and_harmonics(self) -> None:
        AnalogOutput(
            enabled=True,
            amplitude=0.4,
            harmonic1_amplitude=0.05,
            harmonic2_amplitude=0.05,
        ).validate("Ia")

        with self.assertRaisesRegex(ValueError, "must not exceed 0.5 A"):
            AnalogOutput(
                enabled=True,
                amplitude=0.4,
                harmonic1_amplitude=0.1,
                harmonic2_amplitude=0.01,
            ).validate("Ia")

        AnalogOutput(
            enabled=True,
            amplitude=10.0,
            harmonic1_amplitude=2.0,
            harmonic2_amplitude=1.0,
        ).validate("Va")

    def test_result_and_di_event_use_their_documented_identifiers(self) -> None:
        result = 2 | (1 << 3) | (12345 << 4)
        event = 1 | (1 << 3) | (12345 << 4)
        self.assertEqual(decode_result(struct.pack("<I", result)), (2, True, 12345))
        self.assertEqual(decode_di_event(struct.pack("<I", event)), (2, True, 12345))

    def test_di_debouncer_rejects_bounces_and_preserves_board_timestamp(self) -> None:
        debouncer = DIEventDebouncer()
        sample = (
            (2, True, 120_548_480),
            (2, False, 120_548_575),
            (2, False, 120_548_588),
            (2, True, 120_548_713),
            (2, True, 120_548_924),
            (2, False, 122_547_904),
            (2, True, 122_553_005),
        )
        self.assertEqual(
            [debouncer.accept(*event) for event in sample],
            [
                120_548_480,
                None,
                None,
                None,
                None,
                122_547_904,
                122_553_005,
            ],
        )

    def test_ssh_uses_selected_host_and_unquoted_known_hosts_path(self) -> None:
        connection = EmWolfConnection(lambda _message: None, lambda *_args: None, lambda _state: None)
        with tempfile.TemporaryDirectory(prefix="wolfeye test ") as directory:
            connection._ssh_known_hosts = Path(directory) / "known hosts"
            with patch("wolfeye.services.emwolf_protocol.subprocess.Popen") as popen:
                process = connection._start_remote_emwolf("192.0.2.25")

        self.assertIs(process, popen.return_value)
        arguments = popen.call_args.args[0]
        self.assertIn("-tt", arguments)
        self.assertNotIn("-T", arguments)
        self.assertIs(popen.call_args.kwargs["stdin"], subprocess.PIPE)
        self.assertIn("root@192.0.2.25", arguments)
        known_hosts_argument = next(
            item for item in arguments if item.startswith("UserKnownHostsFile=")
        )
        self.assertNotIn('"', known_hosts_argument)
        self.assertIn("known hosts", known_hosts_argument)

    def test_disconnect_sends_safe_stop_before_ctrl_c(self) -> None:
        class Socket:
            def __init__(self) -> None:
                self.sent = b""

            def sendall(self, data: bytes) -> None:
                self.sent += data

            def shutdown(self, _how: int) -> None:
                pass

        class Stdin:
            def __init__(self) -> None:
                self.written = ""

            def write(self, value: str) -> None:
                self.written += value

            def flush(self) -> None:
                pass

        class Process:
            def __init__(self) -> None:
                self.stdin = Stdin()

            def poll(self) -> None:
                return None

            def wait(self, timeout: float) -> int:
                del timeout
                return 0

        connection = EmWolfConnection(
            lambda _message: None, lambda *_args: None, lambda _state: None
        )
        sock = Socket()
        process = Process()
        connection._socket = sock
        connection._ssh_process = process  # type: ignore[assignment]

        connection.disconnect()

        self.assertEqual(
            list(FrameDecoder().feed(sock.sent)),
            [(EW_STOP, EW_STOP_TOKEN)],
        )
        self.assertEqual(process.stdin.written, "\x03")


if __name__ == "__main__":
    unittest.main()
