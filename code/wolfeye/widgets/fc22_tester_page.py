"""FC22 Tester — native WolfEye section for the Final Inspection Form.

Follows the operator workflow of the validated form-driven draft:

    Setup -> Form Data -> Run Test -> Report

and appears beside the existing EmWolf tab using the same company visual
language (``wolfeye.styles``). The tester owns **no** device connections:

- DUT identity / Software Version arrive from ``DeviceService`` over the
  existing LAN path (``connection_changed``), never from a second socket.
- Protection testing remains the job of the existing EmWolf section; the
  tester only records its results.
- The checklist PDF and printing are produced from the values actually
  entered/recorded in this session; no demo values are inserted.

The workflow steps are internal widgets of one compact page (mirroring the
printed-form structure DUT INFO / ANALOG / POWER / DIGITAL / COMM /
PROTECTION / FUNCTION / FINAL) — the operator never navigates 100+ pages.
"""

from __future__ import annotations

from collections.abc import Mapping

import json
import copy
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wolfeye.branding import PRODUCT_NAME
from wolfeye.qt import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColor,
    QHeaderView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QObject,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
    QTimer,
    Signal,
)

from wolfeye.models import DeviceInfo
from wolfeye.widgets.fc22_lot_editor import TestLotEditorDialog
from wolfeye.services.fc22_input_adapters import BenchTcpAdapter, validate_bench_lot_source
from wolfeye.services.fc22_autofill import snapshot_readings
from wolfeye.services.emwolf_protocol import DEFAULT_HOST, DEFAULT_PORT
from wolfeye.services.fc22_form_pdf import fill_form
from wolfeye.services.fc22_session import Fc22Session, Fc22SessionStore
from wolfeye.services.fc22_test_lot import TestLotEngine, load_lot, validate_lot
from wolfeye.services.windows_pdf_printer import print_pdf_to_default_printer

RESULT_CHOICES = ("PASS", "FAIL", "UNKNOWN")
BOOLEAN_CHOICES = ("TRUE", "FALSE", "UNKNOWN")
NA = "-"

PRODUCT_TYPES = (
    "LCU",
    "Pole-mounted RTU",
    "Pad-Mounted RTU",
    "Recloser Control",
    "Disjoncteur control",
)
MODEM_TYPES = ("C3243", "PR300-4G", "UHF", "M104", "Internal", "Others", NA)
BATTERY_TYPES = ("VRLA", "LFP", NA)
APPEARANCE_TYPES = ("Accepted", "Rejected", NA)


@dataclass(frozen=True)
class TestField:
    """One RUN TEST checklist item."""

    key: str
    label: str
    kind: str = "text"          # text / result / boolean
    placeholder: str = "Enter value"


@dataclass(frozen=True)
class TestSection:
    """One printed-form group of RUN TEST items."""

    key: str
    title: str
    domain: str
    fields: tuple[TestField, ...]


def _result(key: str, label: str) -> TestField:
    return TestField(key, label, kind="result")


def _boolean(key: str, label: str) -> TestField:
    return TestField(key, label, kind="boolean")


def _text(key: str, label: str, placeholder: str = "Enter value") -> TestField:
    return TestField(key, label, kind="text", placeholder=placeholder)


# Section keys follow the printed checklist order. The domain tags keep the
# eight-domain architecture (DUT INFO / ANALOG / POWER / DIGITAL / COMM /
# PROTECTION / FUNCTION / FINAL) as future automation layer metadata.
RUN_TEST_SECTIONS: tuple[TestSection, ...] = (
    TestSection(
        "voltages", "1 · Voltages", "ANALOG",
        (
            _text("va", "Phase Voltage · Va"), _text("vb", "Phase Voltage · Vb"),
            _text("vc", "Phase Voltage · Vc"), _text("vr", "Phase Voltage · Vr"),
            _text("vs", "Phase Voltage · Vs"), _text("vt", "Phase Voltage · Vt"),
            _text("vab", "Line Voltage · Vab"), _text("vbc", "Line Voltage · Vbc"),
            _text("vac", "Line Voltage · Vac"), _text("vtr", "Line Voltage · Vtr"),
            _text("vst", "Line Voltage · Vst"), _text("vrs", "Line Voltage · Vrs"),
        ),
    ),
    TestSection(
        "currents", "2 · Currents", "ANALOG",
        (
            _text("ia", "Ia"), _text("ib", "Ib"),
            _text("ic", "Ic"), _text("in", "IN"),
        ),
    ),
    TestSection(
        "measurements", "3 · Measurements", "POWER",
        (
            _text("p_active", "P (Active)"), _text("q_reactive", "Q (Reactive)"),
            _text("s_apparent", "S (Apparent)"),
        ),
    ),
    TestSection(
        "freq_pf", "4 · Frequency & Power Factor", "POWER",
        (
            _text("freq_source", "Frequency · Source"), _text("freq_load", "Frequency · Load"),
            _text("power_factor", "Power Factor"),
        ),
    ),
    TestSection(
        "supply", "5 · Supply & Sensors", "DIGITAL",
        (
            _boolean("ac_available", "AC Supply Status"), _boolean("door_true", "Door Sensor"),
            _boolean("lockout_true", "Lock out"),
        ),
    ),
    TestSection(
        "digital_outputs", "6 · Digital Outputs", "DIGITAL",
        (
            _result("do_trip", "Trip"), _result("do_close", "Close"),
            _result("do_battery", "Battery Tester"), _result("do_heater", "Heater"),
        ),
    ),
    TestSection(
        "digital_inputs", "7 · Digital Input Status", "DIGITAL",
        (
            _result("di_open", "Open"), _result("di_close", "Close"),
            _result("di_lock", "LOCK"), _result("di_gas", "GAS"),
        ),
    ),
    TestSection(
        "internal_modem", "8 · Internal Modem", "COMM",
        (
            _result("modem_status", "Status"), _result("sim_card", "Sim card"),
            _result("ip_acquisition", "IP acquisitions"), _text("remote_ip", "Remote IP", "Enter IP / -"),
        ),
    ),
    TestSection(
        "fault_battery", "9 · Fault / Battery / External Modem", "PROTECTION",
        (
            _result("fault_phase_phase", "Fault · Phase-to-Phase"),
            _result("fault_phase_ground", "Fault · Phase-to-Ground"),
            _result("fault_phase_sync", "Fault · Phase Synchronization"),
            _text("charging_voltage", "Battery Charging · Voltage (>25V)", "Enter measured voltage"),
            _text("charging_current", "Battery Charging · Current (>700mA)", "Enter measured current"),
            _boolean("external_modem", "External Modem"),
        ),
    ),
    TestSection(
        "ar_parameters", "10 · AR Parameters", "FUNCTION",
        (
            _text("capacitor_series", "Capacitor Series", "Enter value / -"),
            _text("capacitance", "Capacitance"), _text("voltage_rating", "Voltage Rating"),
            _text("temperature", "Temperature"),
            _text("booster_output_voltage", "Booster Output Voltage"),
            _result("reclose_4_shot", "4-shot reclose"), _result("dcd", "DCD"),
            _text("reset_mode", "Reset Mode", "Enter mode / -"),
            _text("trip_close_voltage", "Trip/Close test voltage"),
            _text("aux_igbt_version", "Aux. IGBT Version", "Enter version / -"),
        ),
    ),
    TestSection(
        "leds", "11 · LEDs", "FINAL",
        (
            _result("inner_lamp", "Inner Lamp"), _result("live_line", "Live-line"),
            _result("dead_line", "Dead-line"), _result("led_indicators", "LED Indicators"),
        ),
    ),
)

RUN_TEST_FIELD_KEYS: tuple[str, ...] = tuple(
    field.key for section in RUN_TEST_SECTIONS for field in section.fields
)

# Operator form fields, printed-form order (rows above "Test items").
FORM_FIELDS: tuple[tuple[str, str, str], ...] = (
    # (key, label, kind) — kind: text | product | modem | battery | appearance
    ("product_type", "Product Type", "product"),
    ("panel_sn", "Panel S/N", "text"),
    ("cubicle_sn", "Cubicle S/N", "text"),
    ("relay_sn", "Relay S/N", "text"),
    ("cable_bundling", "Cable bundling", "text"),
    ("socket_sn", "Socket S/N", "text"),
    ("modem_type", "Modem Type", "modem"),
    ("modem_data_port", "Modem Data Port", "text"),
    ("modem_id", "Modem ID", "text"),
    ("modem_sn", "Modem S/N", "text"),
    ("appearance", "Appearance", "appearance"),
    ("transformer_sn", "Transformer S/N", "text"),
    ("battery_kind", "Battery Type", "battery"),
    ("mfg_date", "MFG Date", "text"),
    ("main_socket", "Main Socket", "text"),
    ("power_socket", "Power Socket", "text"),
)

REQUIRED_FORM_KEYS = tuple(key for key, _label, _kind in FORM_FIELDS)


class _BenchBridge(QObject):
    measurement = Signal(str, str, str, object, str)
    error = Signal(str)


class Fc22TesterPage(QWidget):
    """Native WolfEye FC22 Tester section (Setup → Form Data → Run Test → Report)."""

    log_line = Signal(str)
    emwolf_connect_requested = Signal(str, int)
    emwolf_run_requested = Signal()
    emwolf_setup_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, store: Fc22SessionStore | None = None) -> None:
        super().__init__()
        self.setObjectName("fc22TesterPage")
        self.store = store or Fc22SessionStore()
        self.session: Fc22Session | None = None
        self.current_pdf: Path | None = None
        self._loading = False
        self._lot_engine: TestLotEngine | None = None
        self._lot_path: Path | None = None
        self._latest_inputs: dict[str, dict[str, object]] = {}
        self._input_updated: dict[str, float] = {}
        self._input_samples: dict[str, int] = {}
        self._input_sequence = 0
        self._reading_updated: dict[str, float] = {}
        self._live_device_info: DeviceInfo | None = None
        self._emwolf_connected = False
        self._lot_table_rows: tuple[tuple[str, str], ...] = ()
        self._emwolf_armed = False
        self._manual_overrides: set[str] = set()
        self._bench_bridge = _BenchBridge()
        self._bench_bridge.measurement.connect(self._accept_bench_measurement)
        self._bench_bridge.error.connect(self._bench_error)
        self._bench_adapter = BenchTcpAdapter(
            lambda *_args: None, self._bench_bridge.error.emit,
            on_context_measurement=self._bench_bridge.measurement.emit,
        )

        self.fields: dict[str, QWidget] = {}
        self.test_fields: dict[str, QWidget] = {}

        self._build_ui()
        self._new_session()
        self._show_step(0)
        self._lot_timer = QTimer(self)
        self._lot_timer.setInterval(250)
        self._lot_timer.timeout.connect(self._automation_tick)
        self._lot_timer.start()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2000)
        self._refresh_timer.timeout.connect(self._request_auto_refresh)
        self._refresh_timer.start()

    # ------------------------------------------------------------- UI build
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 5, 8, 5)
        root.setSpacing(5)

        # Step navigation — the four workflow steps, compact like the draft.
        steps_box = QGroupBox("Tester workflow")
        steps_row = QHBoxLayout(steps_box)
        steps_row.setContentsMargins(8, 6, 8, 4)
        steps_row.setSpacing(6)
        self.step_buttons: list[QPushButton] = []
        for index, title in enumerate(("Setup", "Form Data", "Run Test", "Report")):
            button = QPushButton(title)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=index: self._show_step(i))
            self.step_buttons.append(button)
            steps_row.addWidget(button)
        self.session_label = QLabel("No session")
        self.session_label.setObjectName("muted")
        steps_row.addStretch()
        steps_row.addWidget(self.session_label)
        root.addWidget(steps_box)

        self.step_pages: list[QWidget] = []
        self.step_stack = QVBoxLayout()
        stack_holder = QWidget()
        stack_holder.setLayout(self.step_stack)
        root.addWidget(stack_holder, 1)

        # Page 0 — Setup / DUT information
        setup_page = self._build_setup_page()
        # Page 1 — Final Inspection Form Data
        form_page = self._build_form_page()
        # Page 2 — Run Test
        test_page = self._build_test_page()
        # Page 3 — Report
        report_page = self._build_report_page()
        for page in (setup_page, form_page, test_page, report_page):
            self.step_pages.append(page)
            self.step_stack.addWidget(page)

    # -- Setup ------------------------------------------------------------
    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        session_box = QGroupBox("Session")
        session_grid = QGridLayout(session_box)
        session_grid.setHorizontalSpacing(10)
        self.operator_edit = QLineEdit()
        self.operator_edit.setPlaceholderText("Operator name")
        self.work_order_edit = QLineEdit()
        self.work_order_edit.setPlaceholderText("Work order")
        session_grid.addWidget(QLabel("Operator"), 0, 0)
        session_grid.addWidget(self.operator_edit, 0, 1)
        session_grid.addWidget(QLabel("Work order"), 0, 2)
        session_grid.addWidget(self.work_order_edit, 0, 3)

        session_actions = QHBoxLayout()
        session_actions.setSpacing(12)
        session_actions.setContentsMargins(0, 2, 0, 0)
        new_button = QPushButton("New session")
        new_button.clicked.connect(self._new_session)
        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(220)
        for session_id in self.store.list_sessions():
            self.session_combo.addItem(session_id)
        reload_button = QPushButton("Load selected")
        reload_button.clicked.connect(self._load_selected_session)
        history_label = QLabel("History:")
        session_actions.addWidget(new_button)
        session_actions.addSpacing(8)
        session_actions.addWidget(history_label)
        session_actions.addWidget(self.session_combo)
        session_actions.addSpacing(8)
        session_actions.addWidget(reload_button)
        session_actions.addStretch()
        session_grid.addLayout(session_actions, 1, 0, 1, 4)
        layout.addWidget(session_box)

        dut_box = QGroupBox(
            f"DUT information — from the existing {PRODUCT_NAME} LAN connection"
        )
        dut_grid = QGridLayout(dut_box)
        dut_grid.setHorizontalSpacing(10)

        def read_only(field: str, placeholder: str = "-") -> QLineEdit:
            edit = QLineEdit()
            edit.setReadOnly(True)
            edit.setPlaceholderText(placeholder)
            self.fields[field] = edit
            return edit

        self.model_switch = QComboBox()
        self.model_switch.addItems(("FC22AR", "FC22S"))
        self.model_switch.currentTextChanged.connect(self._model_switched)
        self.fields["dut_model"] = self.model_switch

        rows = (
            ("Model", self.model_switch, "IP", read_only("dut_ip")),
            ("Firmware", read_only("firmware", "AUTO from FC22 LAN"), "Hardware", read_only("hardware")),
            ("Build", read_only("build"), "Transport", read_only("transport")),
        )
        for row, (left_label, left_widget, right_label, right_widget) in enumerate(rows):
            dut_grid.addWidget(QLabel(left_label), row, 0)
            dut_grid.addWidget(left_widget, row, 1)
            dut_grid.addWidget(QLabel(right_label), row, 2)
            dut_grid.addWidget(right_widget, row, 3)

        note = QLabel(
            "Identity and Software Version are read over the existing DeviceService LAN "
            f"connection; connect {PRODUCT_NAME} first. The model switch is used only while the "
            "device is offline (same behavior as the EmWolf section)."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(dut_box)
        layout.addWidget(self._build_emwolf_controls())
        layout.addWidget(self._build_lot_settings())
        bench = self._build_bench_settings()
        bench.setVisible(False)
        show_bench = QCheckBox("External equipment adapter")
        show_bench.toggled.connect(bench.setVisible)
        layout.addWidget(show_bench)
        layout.addWidget(bench)
        layout.addWidget(note)
        layout.addStretch()

        continue_button = QPushButton("Continue to Form Data →")
        continue_button.setObjectName("primary")
        continue_button.clicked.connect(lambda: self._show_step(1))
        layout.addWidget(continue_button, 0, Qt.AlignmentFlag.AlignRight)
        return page

    def _build_emwolf_controls(self) -> QWidget:
        group = QGroupBox("EmWolf test board")
        layout = QGridLayout(group)
        self.emwolf_host = QLineEdit(DEFAULT_HOST)
        self.emwolf_port = QSpinBox()
        self.emwolf_port.setRange(1, 65535)
        self.emwolf_port.setValue(DEFAULT_PORT)
        self.emwolf_connect_button = QPushButton("Connect EmWolf")
        self.emwolf_connect_button.clicked.connect(lambda: self.emwolf_connect_requested.emit(self.emwolf_host.text().strip(), self.emwolf_port.value()))
        self.emwolf_run_button = QPushButton("Run EmWolf project")
        self.emwolf_run_button.setEnabled(False)
        self.emwolf_run_button.clicked.connect(self.emwolf_run_requested.emit)
        configure = QPushButton("Configure scenarios")
        configure.clicked.connect(self.emwolf_setup_requested.emit)
        self.emwolf_state = QLabel("Disconnected")
        self.emwolf_feedback = QLabel("No confirmed EmWolf result in this session")
        self.auto_refresh = QCheckBox("Update DUT measurements automatically while Tester is open")
        self.auto_refresh.setChecked(True)
        refresh = QPushButton("Read DUT measurements")
        refresh.clicked.connect(self.refresh_requested.emit)
        for col, widget in enumerate((QLabel("Host"), self.emwolf_host, QLabel("Port"), self.emwolf_port,
                                      self.emwolf_connect_button, self.emwolf_run_button, configure)):
            layout.addWidget(widget, 0, col)
        layout.addWidget(self.emwolf_state, 1, 0, 1, 2)
        layout.addWidget(self.emwolf_feedback, 1, 2, 1, 5)
        layout.addWidget(self.auto_refresh, 2, 0, 1, 5)
        layout.addWidget(refresh, 2, 5, 1, 2)
        return group

    def set_emwolf_board_state(self, connected: bool, host: str, port: int) -> None:
        self._emwolf_connected = connected
        if not connected:
            self._emwolf_armed = False
        self.emwolf_host.setText(host)
        self.emwolf_port.setValue(port)
        self.emwolf_host.setEnabled(not connected)
        self.emwolf_port.setEnabled(not connected)
        self.emwolf_connect_button.setText("Disconnect EmWolf" if connected else "Connect EmWolf")
        self.emwolf_run_button.setEnabled(connected)
        self.emwolf_state.setText("Connected" if connected else "Disconnected")

    def _request_auto_refresh(self) -> None:
        if self.isVisible() and self.auto_refresh.isChecked() and self._live_device_info and self._live_device_info.connected:
            self.refresh_requested.emit()


    def _build_lot_settings(self) -> QWidget:
        """Compact test settings; the advanced editor exposes the full JSON."""
        group = QGroupBox("Test Lot Configuration")
        grid = QGridLayout(group)
        self.lot_label = QLabel("No active test lot")
        self.lot_label.setObjectName("muted")
        load_button = QPushButton("Load JSON")
        load_button.clicked.connect(self._load_lot_dialog)
        edit_button = QPushButton("Edit JSON")
        edit_button.clicked.connect(self._edit_lot_json)
        save_button = QPushButton("Save JSON As")
        save_button.clicked.connect(self._save_lot_json)
        grid.addWidget(self.lot_label, 0, 0, 1, 2)
        grid.addWidget(load_button, 0, 2)
        grid.addWidget(edit_button, 0, 3)
        grid.addWidget(save_button, 0, 4)

        self.lot_test_combo = QComboBox()
        self.lot_test_combo.currentIndexChanged.connect(self._lot_test_selected)
        self.lot_expected = QLineEdit()
        self.lot_expected.setPlaceholderText("Expected value")
        self.lot_tolerance = QLineEdit()
        self.lot_tolerance.setPlaceholderText("Absolute tolerance")
        self.lot_stable = QCheckBox("Check stability (5 samples)")
        self.lot_stable_spread = QLineEdit()
        self.lot_stable_spread.setPlaceholderText("Max spread")
        self.lot_stable.toggled.connect(self._lot_stability_toggled)
        apply_button = QPushButton("Apply settings")
        apply_button.clicked.connect(self._apply_lot_settings)
        self.lot_apply_button = apply_button
        grid.addWidget(QLabel("Test"), 1, 0)
        grid.addWidget(self.lot_test_combo, 1, 1, 1, 2)
        grid.addWidget(QLabel("Expected"), 2, 0)
        grid.addWidget(self.lot_expected, 2, 1)
        grid.addWidget(QLabel("Tolerance (+/-)"), 2, 2)
        grid.addWidget(self.lot_tolerance, 2, 3)
        grid.addWidget(self.lot_stable, 3, 1)
        grid.addWidget(self.lot_stable_spread, 3, 2)
        grid.addWidget(apply_button, 3, 3)

        hint = QLabel("Full editor: create tests, choose inputs and combine acceptance filters.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        create_button = QPushButton("New Lot")
        create_button.clicked.connect(lambda: self._configure_lot(new=True))
        configure_button = QPushButton("Configure Filters...")
        configure_button.setObjectName("primary")
        configure_button.clicked.connect(self._configure_lot)
        grid.addWidget(hint, 4, 0, 1, 2)
        grid.addWidget(create_button, 4, 2)
        grid.addWidget(configure_button, 4, 3, 1, 2)
        self._refresh_lot_settings()
        return group

    def _build_bench_settings(self) -> QWidget:
        group = QGroupBox("External Test Bench | JSON TCP")
        grid = QGridLayout(group)
        self.bench_host = QLineEdit("127.0.0.1")
        self.bench_port = QLineEdit("6767")
        self.bench_host.setToolTip("Loopback by default; LAN binding requires a trusted isolated network")
        self.bench_token = QLineEdit()
        self.bench_token.setReadOnly(True)
        self.bench_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.bench_token.setPlaceholderText("Created when adapter starts")
        copy_token = QPushButton("Copy token")
        copy_token.clicked.connect(lambda: QApplication.clipboard().setText(self.bench_token.text()))
        self.bench_status = QLabel("Stopped")
        self.bench_status.setObjectName("muted")
        self.bench_button = QPushButton("Start listener")
        self.bench_button.clicked.connect(self._toggle_bench)
        grid.addWidget(QLabel("Bind IP"), 0, 0)
        grid.addWidget(self.bench_host, 0, 1)
        grid.addWidget(QLabel("Port"), 0, 2)
        grid.addWidget(self.bench_port, 0, 3)
        grid.addWidget(self.bench_button, 0, 4)
        grid.addWidget(QLabel("Session token"), 1, 0)
        grid.addWidget(self.bench_token, 1, 1, 1, 2)
        grid.addWidget(copy_token, 1, 3)
        grid.addWidget(self.bench_status, 1, 4)
        note = QLabel("Length-prefixed JSON. Only fields configured in the active lot are accepted. "
                      "Use a trusted LAN for non-loopback binding; never expose this port to the Internet.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        grid.addWidget(note, 2, 0, 1, 5)
        return group

    def _toggle_bench(self) -> None:
        if self._bench_adapter.running:
            self._stop_bench()
            return
        if self.session is None or self._lot_engine is None:
            QMessageBox.warning(self, "Test Bench", "Select a valid Test Lot before starting.")
            return
        try:
            port = int(self.bench_port.text())
            host = self.bench_host.text().strip()
            actual_port = self._bench_adapter.start(self.session.session_id, host, port)
        except (ValueError, OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "Test Bench", str(exc))
            return
        self.bench_token.setText(self._bench_adapter.token)
        self.bench_port.setText(str(actual_port))
        self.bench_status.setText(f"Listening on {host}:{actual_port}")
        self.bench_button.setText("Stop listener")
        self.bench_host.setEnabled(False)
        self.bench_port.setEnabled(False)
        self._lot_engine.reset_channel("external")
        self._latest_inputs.pop("external", None)
        self._evaluate_lot({})

    def _stop_bench(self) -> None:
        self._bench_adapter.stop()
        self.bench_token.clear()
        self.bench_status.setText("Stopped")
        self.bench_button.setText("Start listener")
        self.bench_host.setEnabled(True)
        self.bench_port.setEnabled(True)

    def _bench_error(self, message: str) -> None:
        self.bench_status.setText(message)
        self.log_line.emit(message)

    def _accept_bench_measurement(self, session_id: str, token: str, field: str, value: object, unit: str) -> None:
        if self.session is None or self._lot_engine is None or not self._bench_adapter.running:
            return
        if (session_id != self.session.session_id or token != self._bench_adapter.token
                or self.session.dut_model != self._lot_engine.lot["device_model"]):
            return
        try:
            validate_bench_lot_source(self._lot_engine.lot, field, unit)
        except ValueError as exc:
            self._bench_error(f"Bench input rejected: {exc}")
            return
        self._evaluate_lot({"external": {field: value}})

    def on_emwolf_run_started(self, model: str) -> None:
        self._save_current()
        self._emwolf_armed = bool(
            self.session and model == self.session.dut_model
            and (self._lot_engine is None or model == self._lot_engine.lot["device_model"])
        )
        if not self._emwolf_armed:
            return
        self.session.emwolf_results.clear()
        self.emwolf_feedback.setText("EmWolf run started; waiting for confirmed feedback")
        self.store.save()
        self._latest_inputs.pop("emwolf", None)
        for key in list(self._input_updated):
            if key.startswith("emwolf."):
                self._input_updated.pop(key, None)
                self._input_samples.pop(key, None)
        if self._lot_engine is not None:
            # Restart only EmWolf-dependent filters; preserve other test history.
            self._lot_engine.reset_channel("emwolf")
            self._evaluate_lot({})

    def on_emwolf_result(self, model: str, values: object) -> None:
        if not self._emwolf_armed or self.session is None:
            return
        if model != self.session.dut_model or not isinstance(values, Mapping):
            return
        self.session.emwolf_results.update(values)
        self.emwolf_feedback.setText("EmWolf feedback: " + "; ".join(
            f"{point.split('.')[0]} = {value:g} ms" for point, value in self.session.emwolf_results.items()
            if point.endswith(".trip_time_ms") and type(value) in (int, float)
        ))
        self.store.save()
        self._evaluate_lot({"emwolf": values})
        self._refresh_test_status()

    def _refresh_lot_settings(self) -> None:
        lot = self.session.test_lot if self.session is not None else {}
        tests = lot.get("tests", []) if lot else []
        self.lot_label.setText(
            f"{lot['lot_id']} | {lot['device_model']} | {len(tests)} tests"
            if lot else "No active test lot - load a versioned JSON file"
        )
        blocked = self.lot_test_combo.blockSignals(True)
        selected = self.lot_test_combo.currentData()
        self.lot_test_combo.clear()
        for test in tests:
            self.lot_test_combo.addItem(f"{test['id']} ({test['report_field']})", test["id"])
        pos = self.lot_test_combo.findData(selected)
        self.lot_test_combo.setCurrentIndex(max(pos, 0) if tests else -1)
        self.lot_test_combo.blockSignals(blocked)
        self._lot_test_selected()

    def _lot_test_selected(self, *_args) -> None:
        lot = self.session.test_lot if self.session is not None else {}
        selected = self.lot_test_combo.currentData()
        test = next((t for t in lot.get("tests", []) if t["id"] == selected), None)
        filters = test["filters"] if test else []
        rang = next((f for f in filters if f["type"] == "range"), None)
        tol = next((f for f in filters if f["type"] == "tolerance" and f.get("mode", "absolute") == "absolute"), None)
        numeric = bool(rang or tol)
        expected = test.get("expected", "") if test else ""
        if rang and expected == "":
            expected = (rang["min"] + rang["max"]) / 2
        delta = (rang["max"] - rang["min"]) / 2 if rang else tol["limit"] if tol else ""
        self.lot_expected.setText(str(expected))
        self.lot_tolerance.setText(str(delta))
        stable = next((f for f in filters if f["type"] == "stable"), None)
        self.lot_stable_spread.setText(str(stable["max_spread"]) if stable else "")
        self.lot_stable.setChecked(stable is not None)
        for control in (self.lot_expected, self.lot_tolerance, self.lot_stable, self.lot_apply_button):
            control.setEnabled(numeric)
        self._lot_stability_toggled()

    def _lot_stability_toggled(self, *_args) -> None:
        self.lot_stable_spread.setEnabled(self.lot_stable.isEnabled() and self.lot_stable.isChecked())

    def _activate_lot(self, lot: dict, path: Path | None = None) -> None:
        if self.session is None:
            return
        validated = validate_lot(lot, set(RUN_TEST_FIELD_KEYS))
        connected = bool(self.session.transport) and "Offline" not in self.session.transport
        if connected and self.session.dut_model != validated["device_model"]:
            raise ValueError("The selected test lot does not match the connected DUT model")
        self._stop_bench()
        self._save_current()
        # Never leak values or verdicts from one test configuration into another.
        for key in self.session.auto_fields:
            self.session.test_data.pop(key, None)
        self.session.auto_fields.clear()
        self.session.test_results.clear()
        self.session.test_lot = validated
        if not connected:
            self.session.dut_model = validated["device_model"]
            blocked = self.model_switch.blockSignals(True)
            self.model_switch.setCurrentText(validated["device_model"])
            self.model_switch.blockSignals(blocked)
        self._lot_engine = TestLotEngine(validated, set(RUN_TEST_FIELD_KEYS))
        self._latest_inputs.clear()
        self._input_updated.clear()
        self._input_samples.clear()
        self._emwolf_armed = False
        self._manual_overrides.clear()
        self._clear_observations()
        self.session.emwolf_results.clear()
        self._lot_path = path
        self.store.save()
        self._refresh_lot_settings()
        # Clear visible values before _show_section saves the outgoing widgets.
        self._loading = True
        try:
            for key, widget in self.test_fields.items():
                self._set_widget_value(widget, self.session.test_data.get(key, ""))
        finally:
            self._loading = False
        self._show_section(max(0, self.section_list.currentRow()))
        self._refresh_report_summary()

    def _configure_lot(self, new: bool = False) -> None:
        if self.session is None:
            return
        fields = [(field.key, field.label) for section in RUN_TEST_SECTIONS for field in section.fields]
        dialog = TestLotEditorDialog(
            None if new else self.session.test_lot or None,
            self.session.dut_model,
            fields,
            parent=self,
            build=int(self.session.build) if self.session.build and self.session.transport != "Offline" else None,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.lot is None:
            return
        try:
            self._activate_lot(dialog.lot)
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Test Lot", str(exc))

    def _load_lot_dialog(self) -> None:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        chosen, _ = QFileDialog.getOpenFileName(self, "Load FC22 Test Lot", str(base / "test_lots"), "JSON files (*.json)")
        if not chosen:
            return
        try:
            self._activate_lot(load_lot(chosen, set(RUN_TEST_FIELD_KEYS)), Path(chosen))
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid test lot", str(exc))

    def _edit_lot_json(self) -> None:
        if self.session is None or not self.session.test_lot:
            QMessageBox.information(self, "Test Lot", "Load a JSON test lot first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Test Lot JSON")
        dialog.resize(760, 570)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setPlainText(json.dumps(self.session.test_lot, indent=2, ensure_ascii=False))
        layout.addWidget(editor)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._activate_lot(json.loads(editor.toPlainText()), None)
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid test lot", str(exc))

    def _save_lot_json(self) -> None:
        if self.session is None or not self.session.test_lot:
            QMessageBox.information(self, "Test Lot", "Load a JSON test lot first.")
            return
        chosen, _ = QFileDialog.getSaveFileName(self, "Save Test Lot", "", "JSON files (*.json)")
        if not chosen:
            return
        try:
            path = Path(chosen)
            path.write_text(json.dumps(self.session.test_lot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            self._lot_path = path
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))

    def _apply_lot_settings(self) -> None:
        if self.session is None or not self.session.test_lot:
            return
        lot = json.loads(json.dumps(self.session.test_lot))
        selected = self.lot_test_combo.currentData()
        test = next((t for t in lot["tests"] if t["id"] == selected), None)
        if test is None:
            return
        try:
            expected = float(self.lot_expected.text())
            tolerance = float(self.lot_tolerance.text())
            if not math.isfinite(expected) or not math.isfinite(tolerance) or tolerance < 0:
                raise ValueError("Expected and tolerance must be finite; tolerance cannot be negative")
            test["expected"] = expected
            for filt in test["filters"]:
                if filt["type"] == "range":
                    filt["min"], filt["max"] = expected - tolerance, expected + tolerance
                elif filt["type"] == "tolerance" and filt.get("mode", "absolute") == "absolute":
                    filt["limit"] = tolerance
            test["filters"] = [f for f in test["filters"] if f["type"] != "stable"]
            if self.lot_stable.isChecked():
                spread = float(self.lot_stable_spread.text())
                if not math.isfinite(spread) or spread < 0:
                    raise ValueError("Max spread must be finite and nonnegative")
                test["filters"].append({"type": "stable", "samples": 5, "max_spread": spread})
            self._activate_lot(lot)
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))

    def _restore_lot(self) -> None:
        self._lot_engine = None
        self._lot_path = None
        self._latest_inputs.clear()
        self._input_updated.clear()
        self._input_samples.clear()
        self._emwolf_armed = False
        self._manual_overrides.clear()
        self._reading_updated.clear()
        if self.session and self.session.test_lot:
            try:
                self._lot_engine = TestLotEngine(self.session.test_lot, set(RUN_TEST_FIELD_KEYS))
                for result in self.session.test_results.values():
                    source = result.get("source", "")
                    if source.startswith(("emwolf.", "external.")) and result.get("status") in ("PASS", "FAIL"):
                        if result.get("value") is not None:
                            channel, point = source.split(".", 1)
                            self._latest_inputs.setdefault(channel, {})[point] = result["value"]
            except (ValueError, TypeError):
                # Invalid older session: never silently execute stale test rules.
                pass
        self._refresh_lot_settings()

    def _update_observation_widgets(self, fields: set[str]) -> None:
        self._loading = True
        try:
            for key in fields:
                if key in self.test_fields:
                    self._set_widget_value(self.test_fields[key], self.session.test_data.get(key, ""))
        finally:
            self._loading = False
        self._refresh_test_status()

    def _clear_observations(self) -> None:
        self._reading_updated.clear()
        if self.session is None:
            return
        fields = set(self.session.auto_readings)
        for key in fields:
            if key in self.session.auto_fields:
                self.session.test_data.pop(key, None)
                self.session.auto_fields.remove(key)
        self.session.auto_readings.clear()
        if fields:
            self._update_observation_widgets(fields)

    def _apply_observations(self, readings: dict[str, dict[str, object]]) -> None:
        controlled = {test["report_field"] for test in self.session.test_lot.get("tests", [])}
        changed = set(self.session.auto_readings) - set(readings)
        for key in changed:
            self.session.auto_readings.pop(key, None)
            self._reading_updated.pop(key, None)
            if key in self.session.auto_fields:
                self.session.test_data.pop(key, None)
                self.session.auto_fields.remove(key)
        for key, reading in readings.items():
            if key in controlled:
                continue
            self.session.auto_readings[key] = {**reading, "model": self.session.dut_model, "ip": self.session.dut_ip}
            self._reading_updated[key] = time.monotonic()
            self.session.test_data[key] = str(reading["value"])
            self._manual_overrides.discard(key)
            if key not in self.session.auto_fields:
                self.session.auto_fields.append(key)
            changed.add(key)
        if changed:
            self._update_observation_widgets(changed)
            self.store.save()

    def _automation_tick(self) -> None:
        if self.session is not None:
            maximum = self.session.test_lot.get("max_age_seconds", 30)
            expired = {key for key, updated in self._reading_updated.items()
                       if time.monotonic() - updated > maximum}
            for key in expired:
                self._reading_updated.pop(key, None)
                self.session.auto_readings.pop(key, None)
                if key in self.session.auto_fields:
                    self.session.test_data.pop(key, None)
                    self.session.auto_fields.remove(key)
            if expired:
                self._update_observation_widgets(expired)
                self.store.save()
        self._evaluate_lot({})

    def on_measurements(self, snapshot: object) -> None:
        """Consume the existing DeviceService snapshot; no new LAN connection."""
        if self.session is None or self._live_device_info is None or not self._live_device_info.connected:
            return
        if not self.session.transport or self.session.transport == "Offline":
            return
        if (self.session.dut_model, self.session.dut_ip, self.session.build) != (
            self._live_device_info.model, self._live_device_info.ip, str(self._live_device_info.build or "")
        ):
            return
        self._apply_observations(snapshot_readings(snapshot))
        if self._lot_engine is None or self.session.dut_model != self._lot_engine.lot["device_model"]:
            return
        self._evaluate_lot({
            "analog": snapshot.analog,
            "binary": snapshot.binary,
            "counters": snapshot.counters,
        }, snapshot.timestamp)

    def apply_external_test_values(self, values: Mapping[str, object]) -> None:
        """Optional test-bench adapter. Values are still checked by the same lot."""
        if self._lot_engine is not None and self.session is not None:
            if self.session.dut_model == self._lot_engine.lot["device_model"]:
                self._evaluate_lot({"external": dict(values)})

    def _evaluate_lot(self, values: Mapping[str, object], timestamp=None) -> None:
        if self.session is None or self._lot_engine is None:
            return
        received_at = time.monotonic()
        self._input_sequence += 1
        fresh_sources: set[str] = set()
        for channel, items in values.items():
            if isinstance(items, Mapping):
                dest = self._latest_inputs.setdefault(channel, {})
                for point, value in items.items():
                    dest[point] = value
                    self._input_updated[f"{channel}.{point}"] = received_at
                    self._input_samples[f"{channel}.{point}"] = self._input_sequence
                    fresh_sources.add(f"{channel}.{point}")
        max_age = self._lot_engine.lot.get("max_age_seconds", 30)
        for source, updated_at in list(self._input_updated.items()):
            if source.startswith(("emwolf.", "external.")):
                continue  # Procedural test events are retained for the current session.
            if received_at - updated_at > max_age:
                channel, point = source.split(".", 1)
                self._latest_inputs.get(channel, {}).pop(point, None)
                self._input_updated.pop(source, None)
                self._input_samples.pop(source, None)
        active_channels: set[str] = set()
        if self.session.dut_model == self._lot_engine.lot["device_model"]:
            if self.session.transport and self.session.transport != "Offline":
                active_channels.update(("analog", "binary", "counters"))
            if self._bench_adapter.running or self._latest_inputs.get("external"):
                active_channels.add("external")
            if self._emwolf_armed or self._latest_inputs.get("emwolf"):
                active_channels.add("emwolf")
        result_map = self._lot_engine.evaluate(
            self._latest_inputs, source_timestamps=self._input_samples,
            active_channels=active_channels,
        )
        changed_fields: set[str] = set()
        fields = {field.key: field for sec in RUN_TEST_SECTIONS for field in sec.fields}
        for key, result in result_map.items():
            if key in self._manual_overrides:
                if result.source not in fresh_sources:
                    continue
                self._manual_overrides.discard(key)
            previous = self.session.test_results.get(key, {})
            current = result.as_dict()
            if {k: v for k, v in previous.items() if k != "timestamp"} == {k: v for k, v in current.items() if k != "timestamp"}:
                continue
            self.session.test_results[key] = current
            changed_fields.add(key)
            field = fields[key]
            if key in self.session.auto_fields:
                self.session.test_data.pop(key, None)
            if result.status in ("PASS", "FAIL") and result.value is not None:
                if field.kind == "result":
                    value = result.status
                elif field.kind == "boolean":
                    if not isinstance(result.value, bool):
                        continue
                    value = str(result.value)
                else:
                    value = str(result.value)
                self.session.test_data[key] = value
                if key not in self.session.auto_fields:
                    self.session.auto_fields.append(key)
        self._loading = True
        try:
            for key, widget in self.test_fields.items():
                if key in changed_fields:
                    self._set_widget_value(widget, self.session.test_data.get(key, ""))
        finally:
            self._loading = False
        if changed_fields:
            self.store.save()
            self._refresh_test_status()

    # -- Form Data ----------------------------------------------------------
    def _build_form_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        for index, (key, label, kind) in enumerate(FORM_FIELDS):
            row, col = divmod(index, 4)
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)
            caption = QLabel(label)
            caption.setObjectName("muted")
            widget: QWidget
            if kind == "product":
                widget = QComboBox()
                widget.addItem("Select…", "")
                for value in PRODUCT_TYPES:
                    widget.addItem(value, value)
                widget.currentIndexChanged.connect(self._form_changed)
            elif kind == "modem":
                widget = QComboBox()
                widget.addItem("Select…", "")
                for value in MODEM_TYPES:
                    widget.addItem(value, value)
                widget.currentIndexChanged.connect(self._form_changed)
            elif kind == "battery":
                widget = QComboBox()
                widget.addItem("Select…", "")
                for value in BATTERY_TYPES:
                    widget.addItem(value, value)
                widget.currentIndexChanged.connect(self._form_changed)
            elif kind == "appearance":
                widget = QComboBox()
                widget.addItem("Select…", "")
                for value in APPEARANCE_TYPES:
                    widget.addItem(value, value)
                widget.currentIndexChanged.connect(self._form_changed)
            else:
                widget = QLineEdit()
                widget.setPlaceholderText(f"Required · '{NA}' if N/A")
                widget.textChanged.connect(self._form_changed)
            self.fields[key] = widget
            cell_layout.addWidget(caption)
            cell_layout.addWidget(widget)
            grid.addWidget(cell, row, col)
        grid.setColumnStretch(4, 1)

        software = self.fields.get("software_version")
        if software is None:
            software = QLineEdit()
            software.setReadOnly(True)
            software.setPlaceholderText("AUTO from FC22 LAN")
            self.fields["software_version"] = software
        version_cell = QWidget()
        version_layout = QVBoxLayout(version_cell)
        version_layout.setContentsMargins(0, 0, 0, 0)
        version_layout.setSpacing(2)
        version_caption = QLabel("Software Version · AUTO")
        version_caption.setObjectName("muted")
        version_layout.addWidget(version_caption)
        version_layout.addWidget(software)
        grid.addWidget(version_cell, (len(FORM_FIELDS) + 3) // 4, 0)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        completeness_row = QHBoxLayout()
        self.form_completeness = QLabel("—")
        self.form_completeness.setStyleSheet("font-weight:700;")
        next_button = QPushButton("Continue to Run Test →")
        next_button.setObjectName("primary")
        next_button.clicked.connect(lambda: self._show_step(2))
        completeness_row.addWidget(self.form_completeness)
        completeness_row.addStretch()
        completeness_row.addWidget(next_button)
        outer.addLayout(completeness_row)
        return page

    # -- Run Test -------------------------------------------------------------
    def _build_test_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        nav_box = QGroupBox("Form test sequence")
        nav_box.setMaximumWidth(260)
        nav = QVBoxLayout(nav_box)
        self.section_list = QListWidget()
        for section in RUN_TEST_SECTIONS:
            self.section_list.addItem(QListWidgetItem(section.title))
        self.section_list.currentRowChanged.connect(self._show_section)
        nav.addWidget(self.section_list, 1)
        hint = QLabel(f"Use '{NA}' where the printed form does not apply.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        nav.addWidget(hint)
        layout.addWidget(nav_box)

        center_box = QGroupBox("RUN TEST — company checklist order")
        center = QVBoxLayout(center_box)
        head = QHBoxLayout()
        self.section_title = QLabel("—")
        head.addWidget(self.section_title)
        head.addStretch()
        self.section_progress = QLabel("—")
        self.section_progress.setObjectName("muted")
        head.addWidget(self.section_progress)
        center.addLayout(head)

        self.field_area = QWidget()
        self.field_grid = QGridLayout(self.field_area)
        self.field_grid.setHorizontalSpacing(12)
        self.field_grid.setVerticalSpacing(8)
        center.addWidget(self.field_area, 1)

        actions = QHBoxLayout()
        self.previous_button = QPushButton("← Previous")
        self.previous_button.clicked.connect(self._previous_section)
        self.next_button = QPushButton("Save & Next →")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self._next_section)
        actions.addWidget(self.previous_button)
        actions.addStretch()
        actions.addWidget(self.next_button)
        center.addLayout(actions)
        layout.addWidget(center_box, 1)

        status_box = QGroupBox("Status")
        status_box.setMinimumWidth(270)
        status_box.setMaximumWidth(330)
        status = QVBoxLayout(status_box)
        self.test_status = QLabel("Filled fields  0 / 0")
        self.section_status = QLabel("Sections  0 / 0")
        self.test_status.setStyleSheet("font-weight:700;")
        status.addWidget(self.test_status)
        status.addWidget(self.section_status)
        self.lot_result_status = QLabel("Test Lot: not loaded")
        self.lot_result_status.setWordWrap(True)
        status.addWidget(self.lot_result_status)
        status.addWidget(QLabel("Measurements & test results"))
        self.lot_result_table = QTableWidget(0, 3)
        self.lot_result_table.setHorizontalHeaderLabels(("Test", "Value", "Verdict"))
        self.lot_result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.lot_result_table.verticalHeader().setVisible(False)
        self.lot_result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lot_result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lot_result_table.setAlternatingRowColors(True)
        self.lot_result_table.setMinimumHeight(170)
        status.addWidget(self.lot_result_table, 1)
        note = QLabel(
            "Result-only items use PASS / FAIL / UNKNOWN; status items use "
            "TRUE / FALSE / UNKNOWN. Measured values are typed exactly as read."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        status.addWidget(note)
        layout.addWidget(status_box)
        return page

    # -- Report ---------------------------------------------------------------
    def _build_report_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        template_box = QGroupBox("Company Final Inspection Checklist")
        template_row = QHBoxLayout(template_box)
        template_row.addWidget(QLabel("Template"))
        self.form_combo = QComboBox()
        self.form_combo.addItem("Sectionalizer / S", "s")
        self.form_combo.addItem("Auto Recloser / A", "a")
        template_row.addWidget(self.form_combo)
        self.generate_button = QPushButton("Generate checklist PDF")
        self.generate_button.setObjectName("primary")
        self.generate_button.clicked.connect(self._generate_form)
        self.open_button = QPushButton("Open PDF")
        self.open_button.clicked.connect(self._open_pdf)
        self.print_button = QPushButton("Print checklist")
        self.print_button.clicked.connect(self._print_pdf)
        self.json_button = QPushButton("Write session JSON")
        self.json_button.clicked.connect(self._write_session_json)
        template_row.addWidget(self.generate_button)
        template_row.addWidget(self.open_button)
        template_row.addWidget(self.print_button)
        template_row.addStretch()
        template_row.addWidget(self.json_button)
        layout.addWidget(template_box)

        self.report_summary = QLabel("—")
        self.report_summary.setObjectName("muted")
        self.report_summary.setWordWrap(True)
        layout.addWidget(self.report_summary)
        layout.addStretch()
        return page

    # ------------------------------------------------------------ navigation
    def _show_step(self, index: int) -> None:
        for i, page in enumerate(self.step_pages):
            page.setVisible(i == index)
        for i, button in enumerate(self.step_buttons):
            button.setChecked(i == index)
        if index == 1:
            self._refresh_form_completeness()
        elif index == 2:
            row = max(0, self.section_list.currentRow())
            self._show_section(row)
        elif index == 3:
            self._refresh_report_summary()

    # ------------------------------------------------------------- session
    def _new_session(self) -> None:
        if hasattr(self, "_bench_adapter"):
            self._stop_bench()
        self._emwolf_armed = False
        self._save_current()
        self.session = self.store.new_session()
        self._apply_session_to_ui()
        if self._live_device_info and self._live_device_info.connected:
            self.set_device_info(self._live_device_info)
        self.current_pdf = None
        self._update_session_label()

    def _load_selected_session(self) -> None:
        session_id = self.session_combo.currentText()
        if not session_id:
            return
        try:
            self.session = self.store.load(session_id)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        self._stop_bench()
        self._emwolf_armed = False
        self._apply_session_to_ui()
        self.current_pdf = None
        self._update_session_label()

    def _apply_session_to_ui(self) -> None:
        if self.session is None:
            return
        self._loading = True
        try:
            self.operator_edit.setText(self.session.operator)
            self.work_order_edit.setText(self.session.work_order)
            for key in ("dut_ip", "firmware", "hardware", "build", "transport"):
                widget = self.fields[key]
                widget.setText(getattr(self.session, key))
            model = self.session.dut_model
            self.model_switch.setEnabled(not bool(self.session.transport) or self.session.transport == "Offline")
            if model in ("FC22AR", "FC22S"):
                blocked = self.model_switch.blockSignals(True)
                self.model_switch.setCurrentText(model)
                self.model_switch.blockSignals(blocked)
            for key, widget in self.fields.items():
                if key in ("dut_ip", "firmware", "hardware", "build", "transport", "dut_model"):
                    continue
                if key == "software_version":
                    continue
                value = self.session.form_data.get(key, "")
                self._set_widget_value(widget, value)
            self.fields["software_version"].setText(self.session.firmware)
            for key, widget in self.test_fields.items():
                self._set_widget_value(widget, self.session.test_data.get(key, ""))
        finally:
            self._loading = False
        self._restore_lot()
        self._refresh_form_completeness()
        self._refresh_test_status()

    def _update_session_label(self) -> None:
        if self.session is None:
            self.session_label.setText("No session")
            return
        started = self.session.started_at.replace("T", " ") if self.session.started_at else ""
        self.session_label.setText(f"{self.session.session_id} · {started}")

    def _save_current(self) -> None:
        if self.session is None or self._loading:
            return
        self.session.operator = self.operator_edit.text().strip()
        self.session.work_order = self.work_order_edit.text().strip()
        for key, widget in self.fields.items():
            if key in ("dut_ip", "firmware", "hardware", "build", "transport", "software_version"):
                # Identity fields are saved via set_device_info below.
                continue
            if key == "dut_model":
                self.session.dut_model = self._widget_value(widget) or self.session.dut_model
                continue
            self.session.form_data[key] = self._widget_value(widget)
        for key, widget in self.test_fields.items():
            self.session.test_data[key] = self._widget_value(widget)
        self.store.save()

    # ---------------------------------------------------------- form helpers
    @staticmethod
    def _widget_value(widget: QWidget) -> object:
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        if isinstance(widget, QComboBox):
            data = widget.currentData()
            return data if data is not None else ""
        return ""

    @staticmethod
    def _set_widget_value(widget: QWidget, value: object) -> None:
        text = "" if value is None else str(value)
        if isinstance(widget, QLineEdit):
            widget.setText(text)
        elif isinstance(widget, QComboBox):
            index = widget.findData(text)
            if index < 0:
                index = widget.findText(text)
            widget.setCurrentIndex(index if index >= 0 else 0)

    def _form_changed(self, *_args) -> None:
        if self._loading:
            return
        self._save_current()
        self._refresh_form_completeness()

    def _model_switched(self, model: str) -> None:
        if self._loading or self.session is None:
            return
        info_connected = bool(self.session.transport) and "Offline" not in self.session.transport
        if info_connected:
            return
        changed = model != self.session.dut_model
        self.session.dut_model = model
        if changed:
            self._stop_bench()
            self._reset_lot_inputs()
        self.store.save()

    def _reset_lot_inputs(self) -> None:
        """A new DUT identity cannot inherit verified values from the old one."""
        self._latest_inputs.clear()
        self._input_updated.clear()
        self._input_samples.clear()
        self._manual_overrides.clear()
        self._emwolf_armed = False
        self._clear_observations()
        if self.session:
            self.session.emwolf_results.clear()
        self.emwolf_feedback.setText("No confirmed EmWolf result in this session")
        if self._lot_engine is not None:
            self._lot_engine = TestLotEngine(self._lot_engine.lot, set(RUN_TEST_FIELD_KEYS))
            self._evaluate_lot({})

    # --------------------------------------------------------- device identity
    def set_device_info(self, info: DeviceInfo) -> None:
        """Adopt the identity already read by the WolfEye DeviceService."""
        self._live_device_info = copy.copy(info)
        if self.session is None:
            return
        old_identity = (self.session.dut_model, self.session.dut_ip, self.session.build)
        was_connected = bool(self.session.transport) and self.session.transport != "Offline"
        self._loading = True
        try:
            live = info.connected
            if live:
                self.session.dut_ip = info.ip
                self.session.firmware = str(info.firmware) if info.firmware else ""
                self.session.hardware = str(info.hardware) if info.hardware else ""
                self.session.build = str(info.build) if info.build else ""
                self.session.transport = info.transport
                if info.model in ("FC22AR", "FC22S"):
                    self.session.dut_model = info.model
                    self.session.form_data.setdefault("product_type", "")
            else:
                self.session.transport = "Offline"
            self.fields["dut_ip"].setText(self.session.dut_ip)
            self.fields["firmware"].setText(self.session.firmware)
            self.fields["hardware"].setText(self.session.hardware)
            self.fields["build"].setText(self.session.build)
            self.fields["transport"].setText(self.session.transport)
            model = self.session.dut_model
            if model in ("FC22AR", "FC22S"):
                self.model_switch.setCurrentText(model)
            # Software Version form field: filled only from the DUT, never typed.
            if self.session.firmware:
                self.fields["software_version"].setText(self.session.firmware)
            self.session.form_data["software_version"] = self.session.firmware
        finally:
            self._loading = False
        self.model_switch.setEnabled(not info.connected)
        new_identity = (self.session.dut_model, self.session.dut_ip, self.session.build)
        if old_identity != new_identity or was_connected != info.connected:
            self._stop_bench()
            self._reset_lot_inputs()
        self.store.save()
        self._refresh_form_completeness()
        self._refresh_lot_settings()

    # ------------------------------------------------ future DUT test input
    def apply_dut_test_values(self, values: Mapping[str, object]) -> None:
        """Accept RUN TEST values from a future DUT protocol/API.

        This is the single integration boundary for automated test data.
        Manual entry, session persistence, navigation and PDF generation stay
        unchanged. Unknown keys are ignored so an external protocol cannot
        accidentally write outside the FC22 RUN TEST schema.
        """
        if self.session is None:
            return

        accepted = {
            key: value
            for key, value in values.items()
            if key in RUN_TEST_FIELD_KEYS
        }
        if not accepted:
            return

        self.session.test_data.update(accepted)

        # Refresh only fields currently visible in the active section.
        self._loading = True
        try:
            for key, value in accepted.items():
                widget = self.test_fields.get(key)
                if widget is not None:
                    self._set_widget_value(widget, value)
        finally:
            self._loading = False

        self.store.save()
        self._refresh_test_status()

    def apply_dut_test_value(self, key: str, value: object) -> None:
        """Convenience entry point for one future DUT test result."""
        self.apply_dut_test_values({key: value})

    # ------------------------------------------------------------ form page
    def _refresh_form_completeness(self) -> None:
        if self.session is None:
            return
        missing = [
            key for key in REQUIRED_FORM_KEYS
            if not str(self.session.form_data.get(key, "")).strip()
        ]
        done = len(REQUIRED_FORM_KEYS) - len(missing)
        self.form_completeness.setText(f"Operator fields {done}/{len(REQUIRED_FORM_KEYS)}")
        color = "#18864b" if not missing else "#a55b00"
        self.form_completeness.setStyleSheet(f"color:{color}; font-weight:700;")

    # ------------------------------------------------------------ run-test page
    def _show_section(self, row: int) -> None:
        if row < 0 or row >= len(RUN_TEST_SECTIONS):
            return
        self._save_current()
        section = RUN_TEST_SECTIONS[row]
        self.section_title.setText(f"{section.title}   ({section.domain})")
        self.section_progress.setText(f"Section {row + 1} / {len(RUN_TEST_SECTIONS)}")
        while self.field_grid.count():
            item = self.field_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.test_fields.clear()

        for index, field in enumerate(section.fields):
            cell_row, col = divmod(index, 2)
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)
            caption = QLabel(field.label)
            caption.setObjectName("muted")
            widget: QWidget
            if field.kind == "result":
                widget = QComboBox()
                widget.addItem("Select…", "")
                for value in RESULT_CHOICES:
                    widget.addItem(value, value)
                widget.currentIndexChanged.connect(self._test_changed)
            elif field.kind == "boolean":
                widget = QComboBox()
                widget.addItem("Select…", "")
                for label, data in (
                    ("TRUE", "True"), ("FALSE", "False"), ("UNKNOWN", "UNKNOWN"),
                ):
                    widget.addItem(label, data)
                widget.currentIndexChanged.connect(self._test_changed)
            else:
                widget = QLineEdit()
                widget.setPlaceholderText(field.placeholder)
                widget.textChanged.connect(self._test_changed)
            self.test_fields[field.key] = widget
            cell_layout.addWidget(caption)
            cell_layout.addWidget(widget)
            self.field_grid.addWidget(cell, cell_row, col)
        self.field_grid.setColumnStretch(2, 1)

        if self.session is not None:
            self._loading = True
            try:
                for key, widget in self.test_fields.items():
                    value = self.session.test_data.get(key)
                    if value is not None:
                        self._set_widget_value(widget, value)
            finally:
                self._loading = False
        self.previous_button.setEnabled(row > 0)
        last = row == len(RUN_TEST_SECTIONS) - 1
        self.next_button.setText("Save section" if last else "Save & Next →")
        self._refresh_test_status()

    def _test_changed(self, *_args) -> None:
        if self._loading:
            return
        # A direct operator edit is not an automated, device-verified verdict.
        if self.session is not None:
            widget = self.sender()
            for key, control in self.test_fields.items():
                if control is widget and key in self.session.auto_readings:
                    self.session.auto_readings.pop(key, None)
                    self._reading_updated.pop(key, None)
                    if key in self.session.auto_fields:
                        self.session.auto_fields.remove(key)
                if control is widget and key in self.session.test_results:
                    self.session.test_results[key] = {
                        **self.session.test_results[key], "status": "NOT_TESTED",
                        "reason": "operator edited the field; waiting for a fresh measurement",
                        "value": None,
                    }
                    self._manual_overrides.add(key)
                    if key in self.session.auto_fields:
                        self.session.auto_fields.remove(key)
                    break
        self._save_current()
        self._refresh_test_status()

    @staticmethod
    def _filled(value: object) -> bool:
        return value is True or value is False or (
            value is not None and str(value).strip().upper() not in ("", "UNKNOWN", "NOT_TESTED", "INVALID")
        )

    def _refresh_test_status(self) -> None:
        if self.session is None:
            return
        data = self.session.test_data
        filled = sum(1 for key in RUN_TEST_FIELD_KEYS if self._filled(data.get(key)))
        complete_sections = 0
        for section in RUN_TEST_SECTIONS:
            if all(self._filled(data.get(field.key)) for field in section.fields):
                complete_sections += 1
        self.test_status.setText(f"Filled fields  {filled} / {len(RUN_TEST_FIELD_KEYS)}")
        self.section_status.setText(f"Sections  {complete_sections} / {len(RUN_TEST_SECTIONS)}")
        verdicts = [self.session.test_results.get(test["report_field"], {}).get("status", "NOT_TESTED")
                    for test in self.session.test_lot.get("tests", [])]
        self.lot_result_status.setText(
            f"JSON Tests: {verdicts.count('PASS')} PASS / {verdicts.count('FAIL')} FAIL / "
            f"{verdicts.count('NOT_TESTED')} PENDING / {verdicts.count('INVALID')} INVALID"
            if self.session.test_lot else "Measured values fill automatically; select a Test Lot for acceptance verdicts"
        )
        self._refresh_lot_results_table()
        color = "#18864b" if filled == len(RUN_TEST_FIELD_KEYS) else "#a55b00"
        self.test_status.setStyleSheet(f"color:{color}; font-weight:700;")
        current = self.section_list.currentRow()
        for row, section in enumerate(RUN_TEST_SECTIONS):
            done = all(self._filled(data.get(field.key)) for field in section.fields)
            marker = "✓" if done else "○"
            self.section_list.item(row).setText(f"{marker}  {section.title}")
        if current >= 0:
            self.section_list.setCurrentRow(current)

    def _refresh_lot_results_table(self) -> None:
        """Update the native results view without rebuilding it every sample."""
        if self.session is None:
            return
        tests = self.session.test_lot.get("tests", [])
        rows = tuple((test["id"], test["report_field"]) for test in tests)
        rows += tuple((f"Measured: {field}", field) for field in sorted(self.session.auto_readings))
        rows += tuple((f"EmWolf: {point}", point) for point in sorted(self.session.emwolf_results)
                      if point.endswith(".trip_time_ms"))
        if rows != self._lot_table_rows:
            self._lot_table_rows = rows
            self.lot_result_table.setRowCount(len(rows))
            for index, (test_id, _) in enumerate(rows):
                self.lot_result_table.setItem(index, 0, QTableWidgetItem(test_id))
                self.lot_result_table.setItem(index, 1, QTableWidgetItem("-"))
                self.lot_result_table.setItem(index, 2, QTableWidgetItem("NOT TESTED"))
        for index, (label, field) in enumerate(rows):
            result = self.session.test_results.get(field, {})
            if label.startswith("Measured: "):
                result = {**self.session.auto_readings[field], "status": "MEASURED",
                          "reason": f"Observed from {self.session.auto_readings[field]['source']}; acceptance is defined by Test Lot"}
            elif label.startswith("EmWolf: "):
                result = {"value": self.session.emwolf_results[field], "status": "MEASURED",
                          "reason": "Confirmed EWS2 feedback in milliseconds; acceptance is defined by Test Lot"}
            value = result.get("value")
            display_value = "-" if value is None else str(value)
            status = result.get("status", "NOT_TESTED")
            verdict = "PENDING" if status == "NOT_TESTED" else status
            reason = result.get("reason", "No reading yet")
            if result.get("timestamp"):
                reason += f"\nLast evaluated: {result['timestamp']}"
            for column, text in ((1, display_value), (2, verdict)):
                cell = self.lot_result_table.item(index, column)
                if cell.text() != text:
                    cell.setText(text)
                if cell.toolTip() != reason:
                    cell.setToolTip(reason)
            verdict_cell = self.lot_result_table.item(index, 2)
            color = {"PASS": "#24754e", "FAIL": "#a14343", "INVALID": "#98611b"}.get(status, "#647580")
            if verdict_cell.data(Qt.ItemDataRole.UserRole) != status:
                verdict_cell.setForeground(QColor(color))
                verdict_cell.setData(Qt.ItemDataRole.UserRole, status)

    def _previous_section(self) -> None:
        row = self.section_list.currentRow()
        if row > 0:
            self.section_list.setCurrentRow(row - 1)

    def _next_section(self) -> None:
        self._save_current()
        row = self.section_list.currentRow()
        if row < len(RUN_TEST_SECTIONS) - 1:
            self.section_list.setCurrentRow(row + 1)
        else:
            self._show_step(3)

    # ------------------------------------------------------------ report page
    def _refresh_report_summary(self) -> None:
        if self.session is None:
            return
        data = self.session.test_data
        filled = sum(1 for key in RUN_TEST_FIELD_KEYS if self._filled(data.get(key)))
        self.report_summary.setText(
            f"Session {self.session.session_id} · operator {self.session.operator or '—'} · "
            f"DUT {self.session.dut_model or '—'} {self.session.dut_ip or '—'} · "
            f"software {self.session.firmware or '—'} · RUN TEST fields {filled}/{len(RUN_TEST_FIELD_KEYS)}. "
            f"AUTO readings {len(self.session.auto_readings)}; confirmed EmWolf scenarios "
            f"{sum(point.endswith('.trip_time_ms') for point in self.session.emwolf_results)}. "
            "The PDF uses recorded measurements. Automated verdicts and the exact rules "
            "are stored in session.json; missing and invalid measurements remain blank."
        )
        self.generate_button.setEnabled(True)
        self.generate_button.setToolTip("Generate the checklist PDF with the current values.")
        model = (self.session.dut_model or "").upper()
        desired = "a" if model == "FC22AR" else "s" if model == "FC22S" else ""
        if desired:
            index = self.form_combo.findData(desired)
            if index >= 0:
                self.form_combo.setCurrentIndex(index)

    def _form_payload(self) -> dict[str, object]:
        """Exact operator/DUT values for the checklist PDF. No demo data."""
        assert self.session is not None
        values: dict[str, object] = {}
        for key in self.session.form_data:
            values[key] = self.session.form_data[key]
        boolean_keys = {"ac_available", "door_true", "lockout_true", "external_modem"}
        for key, value in self.session.test_data.items():
            if key in boolean_keys:
                normalized = str(value).strip().lower()
                if normalized in ("true", "false"):
                    values[key] = normalized == "true"
                # Unknown and pending readings must not check either PDF box.
            elif isinstance(value, bool):
                values[key] = value
            else:
                values[key] = str(value).strip()
        values["test_date"] = (
            self.session.started_at or datetime.now().astimezone().isoformat(timespec="seconds")
        )[:10]
        # The printed form has ID/SN cells but no separate Data Port cell.
        port = str(values.get("modem_data_port", "")).strip()
        modem_id = str(values.get("modem_id", "")).strip()
        if port:
            values["modem_id"] = f"{port} / {modem_id}" if modem_id else port
        return values

    def _generate_form(self) -> None:
        if self.session is None:
            return
        self._automation_tick()
        self._save_current()
        tests = self.session.test_lot.get("tests", [])
        complete = bool(self._lot_engine and tests
                        and self.session.dut_model == self._lot_engine.lot["device_model"])
        complete = complete and all(
            self.session.test_results.get(test["report_field"], {}).get("status") == "PASS"
            and self.session.test_results[test["report_field"]].get("source") == test["source"]
            for test in tests
        )
        if self.session.test_lot and not complete:
            answer = QMessageBox.question(
                self, "Incomplete test lot",
                "Some automated tests have not passed. The PDF will contain measured "
                "values only and must not be treated as an approved result. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        form = str(self.form_combo.currentData())
        directory = self.store.directory or Path(".")
        output = directory / f"final_inspection_{form.upper()}.pdf"
        try:
            fill_form(form, output, data=self._form_payload())
        except Exception as exc:
            QMessageBox.critical(self, "Checklist", f"Could not generate the PDF:\n{exc}")
            return
        self.current_pdf = output
        self.report_summary.setText(f"Checklist PDF: {output}")

    def _open_pdf(self) -> None:
        if self.current_pdf is None or not self.current_pdf.exists():
            QMessageBox.information(self, "Checklist", "Generate the checklist PDF first.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(self.current_pdf))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.current_pdf)])
            else:
                subprocess.Popen(["xdg-open", str(self.current_pdf)])
        except OSError as exc:
            QMessageBox.critical(self, "Open PDF", str(exc))

    def _print_pdf(self) -> None:
        if self.current_pdf is None or not self.current_pdf.exists():
            QMessageBox.information(self, "Checklist", "Generate the checklist PDF first.")
            return
        if not sys.platform.startswith("win"):
            QMessageBox.information(
                self,
                "Print checklist",
                "Direct printing is Windows-only. Open the PDF and print it from the system viewer on this platform.",
            )
            return
        try:
            from wolfeye.services.windows_pdf_printer import get_default_printer_name

            printer = get_default_printer_name()
        except Exception as exc:
            QMessageBox.critical(self, "Print checklist", str(exc))
            return
        answer = QMessageBox.question(
            self,
            "Print checklist",
            f"Send {self.current_pdf.name} to the Windows default printer?\n\n{printer}",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            used = print_pdf_to_default_printer(self.current_pdf, dpi=300)
            QMessageBox.information(self, "Print checklist", f"Print job sent to: {used}")
        except Exception as exc:
            QMessageBox.critical(self, "Print checklist", str(exc))

    def _write_session_json(self) -> None:
        if self.session is None:
            return
        self._save_current()
        target = (self.store.directory or Path(".")) / "session.json"
        QMessageBox.information(self, "Session JSON", f"Session JSON is stored at:\n{target}")

    def shutdown(self) -> None:
        """Stop the bench listener and persist the operator-owned session."""
        self._lot_timer.stop()
        self._refresh_timer.stop()
        self._stop_bench()
        self._save_current()
