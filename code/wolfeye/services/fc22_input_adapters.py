"""Validated input bridges for external FC22 test equipment and EmWolf results.

Bench wire format: 4-byte network-order length followed by one UTF-8 JSON
object. The server is explicitly started by the operator and binds to loopback
by default; it never connects to, or commands, any piece of equipment.
"""

from __future__ import annotations

import hmac
import json
import math
import re
import secrets
import socket
import socketserver
import struct
import threading
from collections.abc import Callable, Mapping

MAX_FRAME_BYTES = 8192


def _reject_constant(_constant: str) -> None:
    raise ValueError("invalid JSON constant")


_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,79}\Z")
_DEVICE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def validate_bench_message(message: object, *, session_id: str, token: str) -> tuple[str, int, str, object, str]:
    """Return device, sequence, field, scalar value, unit or raise ValueError."""
    if not isinstance(message, dict) or message.get("version") != 1 or type(message.get("version")) is not int:
        raise ValueError("unsupported message version")
    if message.get("session_id") != session_id:
        raise ValueError("session mismatch")
    supplied_token = message.get("token")
    if not isinstance(supplied_token, str) or not hmac.compare_digest(supplied_token, token):
        raise ValueError("invalid bench token")
    if message.get("source") != "testbench" or message.get("type") != "measurement":
        raise ValueError("expected testbench measurement")
    device, field, sequence = message.get("device"), message.get("field"), message.get("sequence")
    if not isinstance(device, str) or not _DEVICE.fullmatch(device):
        raise ValueError("invalid equipment identifier")
    if not isinstance(field, str) or not _FIELD.fullmatch(field):
        raise ValueError("invalid measurement field")
    if type(sequence) is not int or not 0 <= sequence <= 2**63 - 1:
        raise ValueError("invalid sequence number")
    value = message.get("value")
    if type(value) not in (str, int, float, bool):
        raise ValueError("measurement must be a JSON scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("measurement is non-finite")
    if isinstance(value, str) and len(value) > 256:
        raise ValueError("measurement text is too long")
    unit = message.get("unit", "")
    if not isinstance(unit, str) or len(unit) > 32:
        raise ValueError("invalid unit")
    return device, sequence, field, value, unit


class BenchTcpAdapter:
    """Authenticated TCP receiver; callback runs on worker thread, not Qt thread.

    Auth token is ephemeral and never written to session.json. A new listener
    is required for each session. No remote listener is enabled implicitly.
    """

    def __init__(self, on_measurement: Callable[[str, object, str], None],
                 on_error: Callable[[str], None], *,
                 on_context_measurement: Callable[[str, str, str, object, str], None] | None = None) -> None:
        self._on_measurement = on_measurement
        self._on_error = on_error
        self._on_context_measurement = on_context_measurement
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self.token = ""
        self._sequence: dict[str, int] = {}
        self._lock = threading.Lock()
        self._clients: set[socket.socket] = set()
        self._stopped = threading.Event()

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self, session_id: str, host: str = "127.0.0.1", port: int = 6767) -> int:
        if self.running:
            raise RuntimeError("bench adapter already started")
        if not session_id or not host or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("invalid bench binding")
        self.token = secrets.token_urlsafe(24)
        token = self.token
        stopped = self._stopped = threading.Event()
        self._sequence.clear()
        adapter = self

        class Handler(socketserver.BaseRequestHandler):
            def setup(self) -> None:
                with adapter._lock:
                    adapter._clients.add(self.request)

            def finish(self) -> None:
                with adapter._lock:
                    adapter._clients.discard(self.request)

            def handle(self) -> None:
                self.request.settimeout(5)
                while not stopped.is_set():
                    try:
                        header = self._read_exact(4)
                        if header is None:
                            break
                        length = struct.unpack("!I", header)[0]
                        if not 0 < length <= MAX_FRAME_BYTES:
                            raise ValueError("invalid frame length")
                        frame = self._read_exact(length)
                        if frame is None:
                            raise ValueError("truncated frame")
                        message = json.loads(frame.decode("utf-8"), parse_constant=_reject_constant)
                        device, sequence, field, value, unit = validate_bench_message(
                            message, session_id=session_id, token=token
                        )
                        with adapter._lock:
                            if stopped.is_set():
                                break
                            if sequence <= adapter._sequence.get(device, -1):
                                raise ValueError("duplicate or out-of-order sequence")
                            adapter._sequence[device] = sequence
                        if adapter._on_context_measurement is not None:
                            adapter._on_context_measurement(session_id, token, field, value, unit)
                        else:
                            adapter._on_measurement(field, value, unit)
                    except (ValueError, UnicodeError, json.JSONDecodeError, OSError) as error:
                        if not stopped.is_set():
                            adapter._on_error(f"Bench input rejected: {error}")
                        break

            def _read_exact(self, length: int) -> bytes | None:
                received = bytearray()
                while len(received) < length:
                    part = self.request.recv(length - len(received))
                    if not part:
                        if received:
                            raise ValueError("truncated frame")
                        return None
                    received.extend(part)
                return bytes(received)

        class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True
            allow_reuse_address = True
            request_queue_size = 4

        try:
            server = Server((host, port), Handler)
        except OSError:
            self.token = ""
            raise
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self._thread.start()
        return server.server_address[1]

    def stop(self) -> None:
        self._stopped.set()
        with self._lock:
            clients = tuple(self._clients)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)
        self.token = ""
        with self._lock:
            self._sequence.clear()


def emwolf_scenario_values(scenario_index: int, execution: object) -> dict[str, object]:
    """Translate one confirmed EmWolf DI_TOGGLE result; do not invent verdicts.

    Indices are 1-based and match the position of a scenario in its submitted
    project. A finished scenario provides measured time and observed DI state,
    not an automatic PASS. The active JSON test lot defines acceptable limits.
    """
    elapsed = getattr(execution, "trip_time_us", None)
    input_id = getattr(execution, "trip_input", None)
    value = getattr(execution, "trip_value", None)
    if type(scenario_index) is not int or scenario_index < 0:
        raise ValueError("invalid scenario index")
    if type(elapsed) is not int or elapsed < 0 or type(input_id) is not int or not 1 <= input_id <= 4 or type(value) is not bool:
        raise ValueError("not a confirmed DI trip result")
    prefix = f"scenario_{scenario_index + 1}"
    return {
        f"{prefix}.trip_time_ms": elapsed / 1000.0,
        f"{prefix}.di_input": input_id,
        f"{prefix}.di_value": value,
        f"{prefix}.operation": str(getattr(execution, "operation", "") or ""),
        f"{prefix}.completed": True,
    }


def validate_bench_lot_source(lot: Mapping[str, object], field: str, unit: str) -> None:
    """Reject unconfigured bench fields or mismatched engineering units."""
    source = f"external.{field}"
    tests = [test for test in lot["tests"] if test["source"] == source]  # type: ignore[index]
    conditions = [f for test in lot["tests"] for f in test["filters"]  # type: ignore[index]
                  if f["type"] == "condition" and f["source"] == source]
    if not tests and not conditions:
        raise ValueError(f"{source} is not defined in the active lot")
    if any(test.get("unit", "") != unit for test in tests):
        raise ValueError(f"unit mismatch for {source}")
