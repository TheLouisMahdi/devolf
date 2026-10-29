import struct
import socket
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wolfeye.services.emwolf_protocol import (
    DIEventDebouncer,
    EmWolfConnection,
    EW_START,
    EW_RESULT,
    EW_DI_EVENT,
    EW_STOP,
    EW_STOP_TOKEN,
    PING,
    RESPONSE,
    build_frame,
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

    def test_connect_uses_tcp_without_launching_a_process(self) -> None:
        sock = Mock()
        sock.recv.return_value = b""
        states = []
        connection = EmWolfConnection(lambda _message: None, lambda *_args: None, states.append)
        with patch("socket.create_connection", return_value=sock) as connect_tcp, patch("subprocess.Popen") as popen:
            connection._run("192.0.2.25", 666)
        connect_tcp.assert_called_once_with(("192.0.2.25", 666), timeout=5.0)
        popen.assert_not_called()
        self.assertEqual(states, [True, False])
        sock.close.assert_called_once_with()

    def test_disconnect_stops_outputs_without_terminating_a_process(self) -> None:
        connection = EmWolfConnection(lambda _message: None, lambda *_args: None, lambda _state: None)
        sock = Mock()
        connection._socket = sock
        with patch("subprocess.Popen") as popen, patch("subprocess.run") as run_process:
            connection.disconnect()
        self.assertEqual(list(FrameDecoder().feed(sock.sendall.call_args.args[0])), [(EW_STOP, EW_STOP_TOKEN)])
        sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        popen.assert_not_called()
        run_process.assert_not_called()

    def test_same_manually_started_server_accepts_reconnect(self) -> None:
        received = []
        server_errors = []
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(2)
            server.settimeout(5.0)

            def serve():
                try:
                    for _ in range(2):
                        peer, _address = server.accept()
                        with peer:
                            peer.settimeout(5.0)
                            frames = FrameDecoder()
                            while True:
                                data = peer.recv(4096)
                                if not data:
                                    break
                                received.extend(frames.feed(data))
                except Exception as error:
                    server_errors.append(error)

            server_thread = threading.Thread(target=serve, daemon=True)
            server_thread.start()
            connected = threading.Event()
            connection = EmWolfConnection(lambda _message: None, lambda *_args: None,
                                          lambda state: connected.set() if state else connected.clear())
            try:
                for _ in range(2):
                    connection.connect(*server.getsockname())
                    self.assertTrue(connected.wait(5.0))
                    connection.disconnect()
                    connection._thread.join(5.0)
                    self.assertFalse(connection._thread.is_alive())
                    self.assertFalse(connection.connected)
            finally:
                connection.disconnect()
                if connection._thread:
                    connection._thread.join(5.0)
                server_thread.join(5.0)
            self.assertFalse(server_thread.is_alive())
        self.assertEqual(server_errors, [])
        self.assertEqual(received, [(EW_STOP, EW_STOP_TOKEN)] * 2)


class EmWolfHeartbeatTests(unittest.TestCase):
    def test_ping_reply_keeps_connection_without_emitting_measurements(self):
        clock = [0.0]
        sock = Mock()
        reads = [0]
        measurements = []
        states = []

        def receive(_size):
            reads[0] += 1
            if reads[0] == 1:
                clock[0] = 5.0
                raise socket.timeout()
            if reads[0] == 2:
                frame_type, token = list(FrameDecoder().feed(sock.sendall.call_args.args[0]))[0]
                self.assertEqual(frame_type, PING)
                return build_frame(RESPONSE, token + b"\x00")
            return b""

        sock.recv.side_effect = receive
        connection = EmWolfConnection(lambda _message: None,
                                     lambda *args: measurements.append(args), states.append)
        with patch("socket.create_connection", return_value=sock), \
             patch("wolfeye.services.emwolf_protocol.time.monotonic", side_effect=lambda: clock[0]):
            connection._run("127.0.0.1", 666)
        self.assertEqual(sock.sendall.call_count, 1)
        self.assertEqual(measurements, [])
        self.assertEqual(states, [True, False])
        sock.close.assert_called_once_with()

    def test_queued_pong_is_read_before_timeout_after_reader_delay(self):
        clock = [0.0]
        sock = Mock()
        reads = [0]
        logs, states = [], []

        def receive(_size):
            reads[0] += 1
            if reads[0] == 1:
                clock[0] = 5.0
                raise socket.timeout()
            if reads[0] == 2:
                # The reader was descheduled; a valid PONG is queued when it resumes.
                clock[0] = 25.0
                raise socket.timeout()
            if reads[0] == 3:
                return build_frame(RESPONSE, b"\x01\x00")
            return b""

        sock.recv.side_effect = receive
        connection = EmWolfConnection(logs.append, lambda *_args: None, states.append)
        with patch("socket.create_connection", return_value=sock), \
             patch("wolfeye.services.emwolf_protocol.select.select", return_value=([sock], [], [])), \
             patch("wolfeye.services.emwolf_protocol.time.monotonic", side_effect=lambda: clock[0]):
            connection._run("127.0.0.1", 666)
        frames = [frame for call in sock.sendall.call_args_list
                  for frame in FrameDecoder().feed(call.args[0])]
        self.assertNotIn((EW_STOP, EW_STOP_TOKEN), frames)
        self.assertFalse(any("timed out" in message for message in logs))
        self.assertEqual(reads[0], 4)
        self.assertEqual(states, [True, False])

    def test_ready_unrelated_data_cannot_extend_heartbeat_deadline(self):
        clock = [0.0]
        reads = [0]
        sock = Mock()
        logs = []

        def receive(_size):
            reads[0] += 1
            if reads[0] == 1:
                clock[0] = 5.0
                raise socket.timeout()
            if reads[0] == 2:
                clock[0] = 25.0
                raise socket.timeout()
            # A readable socket is insufficient: this is the wrong PING token.
            return build_frame(RESPONSE, b"\x02\x00")

        sock.recv.side_effect = receive
        connection = EmWolfConnection(logs.append, lambda *_args: None, lambda _s: None)
        with patch("socket.create_connection", return_value=sock), \
             patch("wolfeye.services.emwolf_protocol.select.select", return_value=([sock], [], [])), \
             patch("wolfeye.services.emwolf_protocol.time.monotonic", side_effect=lambda: clock[0]):
            connection._run("127.0.0.1", 666)
        frames = [frame for call in sock.sendall.call_args_list
                  for frame in FrameDecoder().feed(call.args[0])]
        self.assertEqual(frames, [(PING, b"\x01"), (EW_STOP, EW_STOP_TOKEN)])
        self.assertEqual(reads[0], 3)
        self.assertEqual(clock[0], 25.0)
        self.assertTrue(any("timed out" in message for message in logs))

    def test_missing_or_wrong_reply_requests_stop_and_disconnects(self):
        for response in [None, b"\x02\x00", b"\x01\x01"]:
            with self.subTest(response=response):
                clock = [0.0]
                sock = Mock()
                logs = []
                states = []

                def receive(_size):
                    clock[0] += 1.0
                    if response is not None and sock.sendall.called:
                        return build_frame(RESPONSE, response)
                    raise socket.timeout()

                sock.recv.side_effect = receive
                connection = EmWolfConnection(logs.append, lambda *_args: None, states.append)
                with patch("socket.create_connection", return_value=sock), \
                     patch("wolfeye.services.emwolf_protocol.select.select", return_value=([], [], [])), \
                     patch("wolfeye.services.emwolf_protocol.time.monotonic", side_effect=lambda: clock[0]):
                    connection._run("127.0.0.1", 666)
                frames = [frame for call in sock.sendall.call_args_list
                          for frame in FrameDecoder().feed(call.args[0])]
                self.assertEqual(frames, [(PING, b"\x01")] * 6 + [(EW_STOP, EW_STOP_TOKEN)])
                self.assertEqual(clock[0], 25.0)  # first PING at 5; fixed deadline at 25.
                self.assertTrue(any("heartbeat reply timed out" in line for line in logs))
                self.assertEqual(states, [True, False])
                self.assertFalse(connection.connected)
                sock.close.assert_called_once_with()

    def test_delayed_reply_recovers_same_socket_without_resetting_measurements(self):
        clock = [0.0]
        sock = Mock()
        logs, states, measurements, trips = [], [], [], []
        reads = [0]
        connection = EmWolfConnection(logs.append, lambda *a: measurements.append(a),
                                     states.append, lambda *a: trips.append(a))
        connection._di_debouncer.reset = Mock(wraps=connection._di_debouncer.reset)
        di_event = build_frame(EW_DI_EVENT, struct.pack("<I", (1 << 3) | (10000 << 4)))
        trip = build_frame(EW_RESULT, struct.pack("<I", 1 | (1 << 3) | (12345 << 4)))

        def receive(_size):
            reads[0] += 1
            if reads[0] == 1:
                clock[0] = 5.0
                return di_event
            if reads[0] == 2:
                clock[0] = 20.0
                raise socket.timeout()
            if reads[0] == 3:
                self.assertEqual(sock.sendall.call_count, 2)
                self.assertEqual(connection._last_di_event, (1, True, 10000))
                self.assertIs(connection._socket, sock)
                self.assertEqual(states, [True])
                self.assertEqual(measurements, [(1, True, 10000)])
                return build_frame(RESPONSE, b"\x01\x00") + trip
            return b""

        sock.recv.side_effect = receive
        with patch("socket.create_connection", return_value=sock) as connect_tcp, \
             patch("wolfeye.services.emwolf_protocol.time.monotonic", side_effect=lambda: clock[0]):
            connection._run("127.0.0.1", 666)
        frames = [frame for call in sock.sendall.call_args_list
                  for frame in FrameDecoder().feed(call.args[0])]
        self.assertEqual(frames, [(PING, b"\x01")] * 2)
        connect_tcp.assert_called_once()
        connection._di_debouncer.reset.assert_called_once()
        self.assertEqual(measurements, [(1, True, 10000), (1, True, 12345)])
        self.assertEqual(trips, [(1, True, 12345)])
        self.assertTrue(any("retrying the same TCP" in line for line in logs))
        self.assertTrue(any("recovered on the same TCP" in line for line in logs))
        self.assertEqual(states, [True, False])

    def test_manual_disconnect_during_grace_stops_immediately(self):
        clock = [0.0]
        sock = Mock()
        connection = EmWolfConnection(lambda _m: None, lambda *_a: None, lambda _s: None)
        reads = [0]

        def receive(_size):
            reads[0] += 1
            if reads[0] == 1:
                clock[0] = 5.0
            elif reads[0] == 2:
                clock[0] = 20.0
            else:
                connection.disconnect()
                raise OSError("deliberate local shutdown")
            raise socket.timeout()

        sock.recv.side_effect = receive
        with patch("socket.create_connection", return_value=sock), \
             patch("wolfeye.services.emwolf_protocol.time.monotonic", side_effect=lambda: clock[0]):
            connection._run("127.0.0.1", 666)
        frames = [frame for call in sock.sendall.call_args_list
                  for frame in FrameDecoder().feed(call.args[0])]
        self.assertEqual(frames, [(PING, b"\x01")] * 2 + [(EW_STOP, EW_STOP_TOKEN)])
        self.assertEqual(clock[0], 20.0)
        sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)

    def test_real_socket_error_during_retry_does_not_reconnect_or_resend_scenario(self):
        clock = [0.0]
        sock = Mock()
        logs = []
        sock.sendall.side_effect = [None, ConnectionResetError("peer reset")]

        def receive(_size):
            clock[0] += 5.0
            raise socket.timeout()

        sock.recv.side_effect = receive
        connection = EmWolfConnection(logs.append, lambda *_a: None, lambda _s: None)
        with patch("socket.create_connection", return_value=sock) as connect_tcp, \
             patch("wolfeye.services.emwolf_protocol.time.monotonic", side_effect=lambda: clock[0]):
            connection._run("127.0.0.1", 666)
        connect_tcp.assert_called_once()
        self.assertEqual(sock.sendall.call_count, 2)
        self.assertTrue(any("peer reset" in line for line in logs))
        self.assertFalse(connection.connected)
        sock.close.assert_called_once()

    def test_project_and_stop_frames_cannot_be_written_concurrently(self):
        entered = threading.Event()
        release = threading.Event()
        writes = []
        errors = []
        sock = Mock()

        def send(data):
            writes.append(list(FrameDecoder().feed(data))[0])
            if len(writes) == 1:
                entered.set()
                if not release.wait(3.0):
                    raise RuntimeError("test writer was not released")

        sock.sendall.side_effect = send
        connection = EmWolfConnection(lambda _message: None, lambda *_args: None,
                                     lambda _state: None)
        connection._socket = sock

        def send_project():
            try:
                connection.send_project(Project(scenarios=[Scenario()]))
            except Exception as error:
                errors.append(error)

        writer = threading.Thread(target=send_project)
        stopper = threading.Thread(target=connection.disconnect)
        writer.start()
        try:
            self.assertTrue(entered.wait(3.0))
            stopper.start()
            self.assertTrue(connection._disconnect_requested.wait(3.0))
            self.assertEqual(len(writes), 1)
        finally:
            release.set()
            writer.join(3.0)
            if stopper.ident is not None:
                stopper.join(3.0)
        self.assertFalse(writer.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual([item[0] for item in writes], [EW_START, EW_STOP])


if __name__ == "__main__":
    unittest.main()
