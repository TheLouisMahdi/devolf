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

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wolfeye.branding import PRODUCT_NAME
from wolfeye.qt import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)

from wolfeye.models import DeviceInfo
from wolfeye.services.fc22_form_pdf import fill_form
from wolfeye.services.fc22_session import Fc22Session, Fc22SessionStore
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


class Fc22TesterPage(QWidget):
    """Native WolfEye FC22 Tester section (Setup → Form Data → Run Test → Report)."""

    log_line = Signal(str)

    def __init__(self, store: Fc22SessionStore | None = None) -> None:
        super().__init__()
        self.setObjectName("fc22TesterPage")
        self.store = store or Fc22SessionStore()
        self.session: Fc22Session | None = None
        self.current_pdf: Path | None = None
        self._loading = False

        self.fields: dict[str, QWidget] = {}
        self.test_fields: dict[str, QWidget] = {}

        self._build_ui()
        self._new_session()
        self._show_step(0)

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
        layout.addWidget(note)
        layout.addStretch()

        continue_button = QPushButton("Continue to Form Data →")
        continue_button.setObjectName("primary")
        continue_button.clicked.connect(lambda: self._show_step(1))
        layout.addWidget(continue_button, 0, Qt.AlignmentFlag.AlignRight)
        return page

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
        status_box.setMaximumWidth(220)
        status = QVBoxLayout(status_box)
        self.test_status = QLabel("Manual fields  0 / 0")
        self.section_status = QLabel("Sections  0 / 0")
        self.test_status.setStyleSheet("font-weight:700;")
        status.addWidget(self.test_status)
        status.addWidget(self.section_status)
        status.addStretch()
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
        self._save_current()
        self.session = self.store.new_session()
        self._apply_session_to_ui()
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
            for key, value in self.session.test_data.items():
                widget = self.test_fields.get(key)
                if widget is not None:
                    self._set_widget_value(widget, value)
        finally:
            self._loading = False
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
        self.session.dut_model = model
        self.store.save()

    # --------------------------------------------------------- device identity
    def set_device_info(self, info: DeviceInfo) -> None:
        """Adopt the identity already read by the WolfEye DeviceService."""
        if self.session is None:
            return
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
        self.store.save()
        self._refresh_form_completeness()

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
        self._save_current()
        self._refresh_test_status()

    @staticmethod
    def _filled(value: object) -> bool:
        return value is True or value is False or (
            value is not None and str(value).strip() != ""
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
        self.test_status.setText(f"Manual fields  {filled} / {len(RUN_TEST_FIELD_KEYS)}")
        self.section_status.setText(f"Sections  {complete_sections} / {len(RUN_TEST_SECTIONS)}")
        color = "#18864b" if filled == len(RUN_TEST_FIELD_KEYS) else "#a55b00"
        self.test_status.setStyleSheet(f"color:{color}; font-weight:700;")
        current = self.section_list.currentRow()
        for row, section in enumerate(RUN_TEST_SECTIONS):
            done = all(self._filled(data.get(field.key)) for field in section.fields)
            marker = "✓" if done else "○"
            self.section_list.item(row).setText(f"{marker}  {section.title}")
        if current >= 0:
            self.section_list.setCurrentRow(current)

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
            "The PDF uses the current values; blank fields remain blank."
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
        for key, value in self.session.test_data.items():
            if isinstance(value, bool):
                values[key] = value
            else:
                text = str(value).strip()
                values[key] = text
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
        self._save_current()
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
        """Company cleanup order: persist operator data only.

        Device connections are owned by ``DeviceService`` / ``EmWolfPage`` and
        are closed by MainWindow.closeEvent as before; this page must not and
        does not stop them.
        """
        self._save_current()
