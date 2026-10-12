"""Session storage for the FC22 Tester section.

Single source of truth for one tester run. The tester owns only operator
data; the DUT connection stays owned by ``DeviceService`` and the EmWolf
connection by ``EmWolfPage`` (no second connection is ever created here).

One session is one directory:

    sessions/FC22-YYYYMMDD-HHMMSS/session.json

The JSON is written atomically on every change so values persist through
navigation and application restarts. Nothing here interprets protocol data;
identity values are copied from ``wolfeye.models.DeviceInfo`` by the UI.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SESSION_PREFIX = "FC22-"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Fc22Session:
    """Operator-owned tester state for one DUT run."""

    session_id: str = field(default_factory=lambda: "")
    started_at: str = field(default_factory=_now_iso)
    ended_at: str | None = None

    # Setup tab — session identity (operator-entered).
    operator: str = ""
    work_order: str = ""

    # DUT info — identity fields read from the WolfEye LAN connection are
    # recorded here verbatim (never typed twice, never invented).
    dut_model: str = ""
    dut_ip: str = ""
    firmware: str = ""
    hardware: str = ""
    build: str = ""
    transport: str = ""

    # Form Data tab — the rows above "Test items" on the printed checklist.
    # Keys and order follow the printed company Final Inspection Form.
    form_data: dict[str, str] = field(default_factory=dict)

    # Run Test tab — the checklist test items. Value fields are free text;
    # result-only fields hold PASS / FAIL / UNKNOWN; boolean status fields
    # hold True / False (persisted as the strings "True"/"False") or "".
    test_data: dict[str, object] = field(default_factory=dict)

    note: str = ""


class Fc22SessionStore:
    """Creates, persists, and lists tester sessions on disk."""

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            if getattr(sys, "frozen", False):
                # Frozen single-file build: keep data beside the executable.
                base = Path(sys.executable).resolve().parent
            else:
                # From source: keep data in the project root next to code/.
                base = Path(__file__).resolve().parents[3]
            root = base / "sessions"
        self.root = Path(root)
        self.session: Fc22Session | None = None

    # ------------------------------------------------------------- sessions
    def new_session(self) -> Fc22Session:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session = Fc22Session(session_id=f"{SESSION_PREFIX}{stamp}")
        self.session = session
        self.save()
        return session

    @property
    def directory(self) -> Path | None:
        if self.session is None:
            return None
        return self.root / self.session.session_id

    def path(self) -> Path | None:
        directory = self.directory
        return None if directory is None else directory / "session.json"

    # ------------------------------------------------------------ persistence
    def save(self) -> None:
        if self.session is None:
            return
        directory = self.directory
        assert directory is not None
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "session.json"
        temporary = target.with_suffix(".json.tmp")
        payload = {
            "session_id": self.session.session_id,
            "started_at": self.session.started_at,
            "ended_at": self.session.ended_at,
            "operator": self.session.operator,
            "work_order": self.session.work_order,
            "dut": {
                "model": self.session.dut_model,
                "ip": self.session.dut_ip,
                "firmware": self.session.firmware,
                "hardware": self.session.hardware,
                "build": self.session.build,
                "transport": self.session.transport,
            },
            "form_data": dict(self.session.form_data),
            "test_data": dict(self.session.test_data),
            "note": self.session.note,
        }
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)

    def load(self, session_id: str) -> Fc22Session:
        source = self.root / session_id / "session.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        dut = payload.get("dut", {})
        session = Fc22Session(
            session_id=str(payload.get("session_id", session_id)),
            started_at=str(payload.get("started_at", "")),
            ended_at=payload.get("ended_at"),
            operator=str(payload.get("operator", "")),
            work_order=str(payload.get("work_order", "")),
            dut_model=str(dut.get("model", "")),
            dut_ip=str(dut.get("ip", "")),
            firmware=str(dut.get("firmware", "")),
            hardware=str(dut.get("hardware", "")),
            build=str(dut.get("build", "")),
            transport=str(dut.get("transport", "")),
            form_data={
                str(key): str(value)
                for key, value in payload.get("form_data", {}).items()
            },
            test_data=dict(payload.get("test_data", {})),
            note=str(payload.get("note", "")),
        )
        self.session = session
        return session

    def list_sessions(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(
            entry.name
            for entry in self.root.iterdir()
            if entry.is_dir() and entry.name.startswith(SESSION_PREFIX)
        )
