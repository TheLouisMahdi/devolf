from __future__ import annotations

import copy
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from wolfeye.qt import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QObject,
    QSize,
    Qt,
    Signal,
    QColor,
    QDoubleValidator,
    QPainter,
    QPen,
)

from wolfeye.models import DeviceInfo
from wolfeye.services.emwolf_protocol import (
    CHANNEL_NAMES,
    CURRENT_CHANNEL_NAMES,
    DEFAULT_HOST,
    DEFAULT_PORT,
    END_TYPES,
    MAX_CURRENT_AMPLITUDE_A,
    MAX_SCENARIOS,
    AnalogOutput,
    DeviceMetadata,
    EmWolfConnection,
    Project,
    Scenario,
    Setup,
    emwolf_default_scenario,
    load_project,
    save_project,
)
from wolfeye.services.emwolf_report import EmWolfRunReport, generate_emwolf_pdf
from wolfeye.services.fc22_input_adapters import emwolf_scenario_values


class _ConnectionBridge(QObject):
    log = Signal(str)
    state = Signal(bool)
    result = Signal(int, bool, int)
    trip = Signal(int, bool, int)


class _DeviceModelSwitch(QAbstractButton):
    """Compact two-state model selector for offline EmWolf operation."""

    model_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Select the device model while LAN identity is unavailable")
        self.setAccessibleName("Device model")
        self.setFixedSize(self.sizeHint())
        self.toggled.connect(self._emit_model)

    def sizeHint(self) -> QSize:
        return QSize(138, 26)

    def model(self) -> str:
        return "FC22S" if self.isChecked() else "FC22AR"

    def set_model(self, model: str) -> None:
        if model not in {"FC22AR", "FC22S"}:
            return
        blocked = self.blockSignals(True)
        self.setChecked(model == "FC22S")
        self.blockSignals(blocked)
        self.update()

    def _emit_model(self) -> None:
        self.model_changed.emit(self.model())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        outer = self.rect().adjusted(1, 1, -1, -1)
        selected = QColor("#087ad1" if self.isEnabled() else "#8295a3")
        painter.setPen(QPen(QColor("#6f818e"), 1))
        painter.setBrush(QColor("#f4f7f9"))
        painter.drawRoundedRect(outer, 12, 12)

        half = outer.width() // 2
        selected_rect = (
            outer.adjusted(half, 0, 0, 0)
            if self.isChecked()
            else outer.adjusted(0, 0, -half, 0)
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(selected)
        painter.drawRoundedRect(selected_rect, 12, 12)

        font = painter.font()
        font.setBold(True)
        font.setPointSize(8)
        painter.setFont(font)
        left = self.rect().adjusted(0, 0, -self.width() // 2, 0)
        right = self.rect().adjusted(self.width() // 2, 0, 0, 0)
        painter.setPen(QColor("#ffffff") if not self.isChecked() else QColor("#445661"))
        painter.drawText(left, Qt.AlignmentFlag.AlignCenter, "FC22AR")
        painter.setPen(QColor("#ffffff") if self.isChecked() else QColor("#445661"))
        painter.drawText(right, Qt.AlignmentFlag.AlignCenter, "FC22S")


class EmWolfPage(QWidget):
    """Qt port of the supplied EmWolf Scenario Tool, preserving its wire format."""

    log_line = Signal(str)
    log_window_requested = Signal()
    test_run_started = Signal(str)
    test_result = Signal(str, object)
    board_state_changed = Signal(bool, str, int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("emwolfPage")
        self.project = Project()
        self._live_device_info: DeviceInfo | None = None
        self._device_model_is_manual = False
        self.execution_report: EmWolfRunReport | None = None
        self.current_index: int | None = None
        self.loading = False
        self.bridge = _ConnectionBridge()
        self.connection = EmWolfConnection(
            self.bridge.log.emit,
            self.bridge.result.emit,
            self.bridge.state.emit,
            self.bridge.trip.emit,
        )
        self._apply_visual_style()
        self._build_ui()
        self.bridge.log.connect(self._log)
        self.bridge.state.connect(self._set_connection_state)
        self.bridge.result.connect(self._show_result)
        self.bridge.trip.connect(self._record_trip)
        self._load_setup()
        self._refresh_scenarios(0)
        self.host.textChanged.connect(lambda: self.publish_board_state())
        self.port.valueChanged.connect(lambda: self.publish_board_state())

    def _apply_visual_style(self) -> None:
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        checked = (root / "assets" / "checkbox-checked.svg").as_posix()
        unchecked = (root / "assets" / "checkbox-unchecked.svg").as_posix()
        arrow = (root / "assets" / "combo-arrow.svg").as_posix()
        self.setStyleSheet(
            f"""
            QWidget#emwolfPage QLineEdit,
            QWidget#emwolfPage QSpinBox {{
                background: #ffffff;
                border: 1px solid #929292;
                border-radius: 2px;
                min-height: 18px;
            }}
            QWidget#emwolfPage QLineEdit {{ padding: 2px 8px; }}
            QWidget#emwolfPage QSpinBox {{ padding: 2px 28px 2px 8px; }}
            QWidget#emwolfPage QLineEdit:focus,
            QWidget#emwolfPage QSpinBox:focus {{
                border: 2px solid #087ad1;
            }}
            QWidget#emwolfPage QLineEdit:focus {{ padding: 1px 7px; }}
            QWidget#emwolfPage QLineEdit#diNameEdit {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 2px;
                padding: 2px 4px;
                font-weight: 600;
            }}
            QWidget#emwolfPage QLineEdit#diNameEdit:hover {{
                background: #f7fafc;
                border-color: #cad6de;
            }}
            QWidget#emwolfPage QLineEdit#diNameEdit:focus {{
                background: #ffffff;
                border: 1px solid #087ad1;
                padding: 2px 4px;
            }}
            QWidget#emwolfPage QSpinBox:focus {{ padding: 1px 27px 1px 7px; }}
            QWidget#emwolfPage QSpinBox#portSpin {{ padding: 2px 8px; }}
            QWidget#emwolfPage QSpinBox#portSpin:focus {{ padding: 1px 7px; }}
            QWidget#emwolfPage QComboBox {{
                background: #ffffff;
                border: 1px solid #737373;
                border-radius: 2px;
                padding: 2px 23px 2px 8px;
                min-height: 18px;
            }}
            QWidget#emwolfPage QComboBox:hover {{
                border-color: #287fbd;
            }}
            QWidget#emwolfPage QComboBox:focus {{
                border: 2px solid #087ad1;
                padding: 1px 22px 1px 7px;
            }}
            QWidget#emwolfPage QComboBox:disabled {{
                color: #737373;
                background: #e9e9e9;
                border-color: #adadad;
            }}
            QWidget#emwolfPage QComboBox::drop-down {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 22px;
                background: #e9e9e9;
                border-left: 1px solid #858585;
            }}
            QWidget#emwolfPage QComboBox::down-arrow {{
                image: url("{arrow}");
                width: 9px;
                height: 6px;
            }}
            QWidget#emwolfPage QCheckBox {{
                spacing: 6px;
            }}
            QWidget#emwolfPage QCheckBox::indicator {{
                width: 16px;
                height: 16px;
            }}
            QWidget#emwolfPage QCheckBox::indicator:unchecked {{
                image: url("{unchecked}");
            }}
            QWidget#emwolfPage QCheckBox::indicator:checked {{
                image: url("{checked}");
            }}
            QWidget#emwolfPage QTableWidget#scenarioTable QHeaderView::section {{
                padding: 5px 8px;
            }}
            QWidget#emwolfPage QTableWidget#scenarioTable::item {{
                padding: 4px 8px;
            }}
            """
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 5, 8, 5)
        root.setSpacing(5)
        self.root_layout = root

        connection_box = QGroupBox("Connection")
        connection_row = QHBoxLayout(connection_box)
        connection_row.setContentsMargins(8, 10, 8, 6)
        connection_row.setSpacing(7)
        self.connection_box = connection_box
        self.connection_row = connection_row
        self.host = QLineEdit(DEFAULT_HOST)
        self.host.setMinimumWidth(125)
        self.host.setMaximumWidth(180)
        self.port = QSpinBox()
        self.port.setObjectName("portSpin")
        self.port.setRange(1, 65535)
        self.port.setValue(DEFAULT_PORT)
        self.port.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.port.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.port.setFixedWidth(78)
        self.connect_button = QPushButton("Connect")
        self.send_button = QPushButton("Send scenarios")
        self.state_label = QLabel("Disconnected")
        self.save_button = QPushButton("Save JSON")
        self.load_button = QPushButton("Load JSON")
        self.pdf_button = QPushButton("Print PDF")
        self.pdf_button.setToolTip(
            "Create a formal A4 report focused on the first DI toggle trip time."
        )
        connection_row.addWidget(QLabel("Host"))
        connection_row.addWidget(self.host)
        connection_row.addWidget(QLabel("Port"))
        connection_row.addWidget(self.port)
        connection_row.addWidget(self.connect_button)
        connection_row.addWidget(self.send_button)
        connection_row.addWidget(self.state_label)
        connection_row.addStretch()
        connection_row.addWidget(self.pdf_button)
        connection_row.addWidget(self.save_button)
        connection_row.addWidget(self.load_button)
        root.addWidget(connection_box)

        device_box = QGroupBox("Device Under Test")
        device_row = QHBoxLayout(device_box)
        device_row.setContentsMargins(10, 8, 10, 7)
        device_row.setSpacing(10)
        self.device_box = device_box
        self.device_model_value = QLabel("Not available")
        self.device_model_value.setStyleSheet("font-weight:700;color:#16324a")
        self.device_details_value = QLabel("FW -  |  HW -  |  Build -")
        self.device_ip_value = QLabel("IP -")
        self.device_transport_value = QLabel("LAN status not read")
        self.device_status_value = QLabel("OFFLINE")
        self.device_status_value.setStyleSheet("color:#667784;font-weight:700")
        self.device_model_switch = _DeviceModelSwitch()
        self.device_model_switch.model_changed.connect(self._set_offline_device_model)
        device_row.addWidget(QLabel("MODEL"))
        device_row.addWidget(self.device_model_value)
        device_row.addSpacing(12)
        device_row.addWidget(self.device_details_value)
        device_row.addSpacing(12)
        device_row.addWidget(self.device_ip_value)
        device_row.addSpacing(12)
        device_row.addWidget(self.device_transport_value)
        device_row.addStretch()
        device_row.addWidget(self.device_model_switch)
        device_row.addSpacing(4)
        device_row.addWidget(self.device_status_value)
        root.addWidget(device_box)
        self._set_offline_device_model(self.device_model_switch.model())

        setup_box = QGroupBox("Setup")
        setup_box.setMaximumHeight(128)
        setup_grid = QGridLayout(setup_box)
        setup_grid.setContentsMargins(8, 7, 8, 4)
        setup_grid.setHorizontalSpacing(8)
        setup_grid.setVerticalSpacing(2)
        setup_grid.setColumnStretch(10, 1)
        self.setup_box = setup_box
        self.setup_grid = setup_grid
        self.offsets: dict[str, QSpinBox] = {}
        for index, name in enumerate(CHANNEL_NAMES):
            label = QLabel(f"{name} offset")
            label.setFixedWidth(104)
            value = QSpinBox()
            value.setRange(0, 65535)
            value.setValue(2048)
            value.setFixedWidth(116)
            value.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            row, pair = divmod(index, 4)
            setup_grid.addWidget(label, row, pair * 2)
            setup_grid.addWidget(value, row, pair * 2 + 1)
            self.offsets[name] = value
        self.sample_time = QLineEdit("8.2")
        self.sample_time.setFixedWidth(90)
        sample_time_label = QLabel("Sample time (us)")
        sample_time_label.setFixedWidth(104)
        setup_grid.addWidget(sample_time_label, 2, 0)
        setup_grid.addWidget(self.sample_time, 2, 1)
        self.di_name_edits: dict[int, QLineEdit] = {}
        self.di_labels: dict[int, QLabel] = {}
        for input_id in range(1, 5):
            name = QLineEdit(f"DI{input_id}")
            name.setObjectName("diNameEdit")
            name.setMaxLength(32)
            name.setFixedWidth(104)
            name.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            name.setToolTip(
                "Click to edit the digital input name used in End type, logs, and reports"
            )
            name.editingFinished.connect(
                lambda input_id=input_id: self._di_name_changed(input_id)
            )
            setup_grid.addWidget(name, 2, input_id * 2)
            state = QLabel("?")
            state.setAlignment(Qt.AlignmentFlag.AlignCenter)
            state.setFixedWidth(46)
            setup_grid.addWidget(state, 2, input_id * 2 + 1)
            self.di_name_edits[input_id] = name
            self.di_labels[input_id] = state
        root.addWidget(setup_box)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(7)
        self.scenario_table = QTableWidget(0, 3)
        self.scenario_table.setObjectName("scenarioTable")
        self.scenario_table.setHorizontalHeaderLabels(["Scenario", "End", "DO"])
        self.scenario_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.scenario_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.scenario_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.scenario_table.verticalHeader().setVisible(False)
        self.scenario_table.verticalHeader().setDefaultSectionSize(30)
        header = self.scenario_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.scenario_table.setColumnWidth(1, 110)
        self.scenario_table.setColumnWidth(2, 60)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.scenario_table)
        button_grid = QGridLayout()
        button_grid.setContentsMargins(0, 0, 0, 0)
        button_grid.setHorizontalSpacing(7)
        button_grid.setVerticalSpacing(6)
        actions = (
            ("Add", self._add),
            ("Add default", self._add_default),
            ("Duplicate", self._duplicate),
            ("Remove", self._remove),
            ("Up", lambda: self._move(-1)),
            ("Down", lambda: self._move(1)),
        )
        for index, (text, callback) in enumerate(actions):
            button = QPushButton(text)
            button.clicked.connect(callback)
            button_grid.addWidget(button, index // 3, index % 3)
        left_layout.addLayout(button_grid)

        editor = QGroupBox("Selected scenario")
        editor_grid = QGridLayout(editor)
        editor_grid.setContentsMargins(10, 14, 10, 8)
        editor_grid.setHorizontalSpacing(8)
        editor_grid.setVerticalSpacing(2)
        self.editor_box = editor
        self.editor_grid = editor_grid
        self.name = QLineEdit()
        self.name.setFixedWidth(240)
        editor_grid.addWidget(QLabel("Name"), 0, 0)
        editor_grid.addWidget(self.name, 0, 1, 1, 2)
        headers = (
            "Channel",
            "On",
            "Amplitude",
            "Frequency",
            "Phase",
            "H1",
            "H1 amp",
            "H2",
            "H2 amp",
        )
        for column, title in enumerate(headers):
            editor_grid.addWidget(QLabel(title), 1, column)
        self.analog_widgets: dict[str, dict[str, QWidget]] = {}
        for row, channel in enumerate(CHANNEL_NAMES, 2):
            enabled = QCheckBox()
            amplitude = self._number_edit(92)
            frequency = self._number_edit(92)
            phase = self._number_edit(76)
            h1_order = QComboBox()
            h1_order.addItems([str(v) for v in range(2, 16)])
            h1_order.setFixedWidth(68)
            h1_amplitude = self._number_edit(88)
            h1_amplitude.setValidator(QDoubleValidator(h1_amplitude))
            h2_order = QComboBox()
            h2_order.addItems([str(v) for v in range(2, 16)])
            h2_order.setFixedWidth(68)
            h2_amplitude = self._number_edit(88)
            h2_amplitude.setValidator(QDoubleValidator(h2_amplitude))
            if channel in CURRENT_CHANNEL_NAMES:
                for current_edit in (amplitude, h1_amplitude, h2_amplitude):
                    current_edit.setValidator(
                        QDoubleValidator(
                            0.0,
                            MAX_CURRENT_AMPLITUDE_A,
                            6,
                            current_edit,
                        )
                    )
                    current_edit.setToolTip(
                        f"Current limit: fundamental + harmonics <= "
                        f"{MAX_CURRENT_AMPLITUDE_A:g} A"
                    )
            widgets = (
                QLabel(channel),
                enabled,
                amplitude,
                frequency,
                phase,
                h1_order,
                h1_amplitude,
                h2_order,
                h2_amplitude,
            )
            for column, widget in enumerate(widgets):
                editor_grid.addWidget(widget, row, column)
            self.analog_widgets[channel] = {
                "enabled": enabled,
                "amplitude": amplitude,
                "frequency": frequency,
                "phase": phase,
                "h1_order": h1_order,
                "h1_amplitude": h1_amplitude,
                "h2_order": h2_order,
                "h2_amplitude": h2_amplitude,
            }
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background:#aaa")
        editor_grid.addWidget(separator, 10, 0, 1, 9)
        editor_grid.setRowMinimumHeight(10, 5)
        editor_grid.addWidget(QLabel("Digital outputs"), 11, 0)
        digital_row = QHBoxLayout()
        digital_row.setContentsMargins(0, 2, 0, 2)
        digital_row.setSpacing(24)
        self.digital_outputs: list[QCheckBox] = []
        digital_output_names = ("DO1 (CLOSE)", "DO2 (TRIP / OPEN)", "DO3", "DO4")
        digital_output_colors = ("#b42318", "#087a20", "", "")
        for name, color in zip(digital_output_names, digital_output_colors):
            checkbox = QCheckBox(name)
            if color:
                checkbox.setStyleSheet(f"color:{color};font-weight:700")
            self.digital_outputs.append(checkbox)
            digital_row.addWidget(checkbox)
        digital_row.addStretch()
        editor_grid.addLayout(digital_row, 11, 1, 1, 8)
        self.end_type = QComboBox()
        self.end_type.addItems(END_TYPES)
        self.end_type.setToolTip(
            "DI_TOGGLE completes on the first valid HIGH or LOW transition."
        )
        self.end_type.setFixedWidth(140)
        self.digital_input = QComboBox()
        self.digital_input.setFixedWidth(130)
        self.digital_input.view().setMinimumWidth(130)
        self.end_value = self._number_edit(110)
        end_row = QHBoxLayout()
        end_row.setContentsMargins(0, 5, 0, 2)
        end_row.setSpacing(12)
        end_row.addWidget(QLabel("End type"))
        end_row.addWidget(self.end_type)
        end_row.addSpacing(28)
        self.digital_input_label = QLabel("Digital input")
        end_row.addWidget(self.digital_input_label)
        end_row.addWidget(self.digital_input)
        end_row.addSpacing(28)
        self.end_value_label = QLabel("Cycles")
        end_row.addWidget(self.end_value_label)
        end_row.addWidget(self.end_value)
        end_row.addStretch()
        editor_grid.addLayout(end_row, 12, 0, 1, 9)
        editor_grid.setRowStretch(13, 1)
        left.setMinimumWidth(240)
        editor.setMinimumWidth(0)
        body_layout.addWidget(left, 3)
        body_layout.addWidget(editor, 7)
        root.addWidget(body, 1)

        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(6, 11, 6, 6)
        log_layout.setSpacing(4)
        self.log_box = log_box
        self.log_layout = log_layout
        log_tools = QHBoxLayout()
        log_tools.addStretch()
        self.open_log_button = QPushButton("Open log window")
        self.open_log_button.clicked.connect(self.log_window_requested)
        log_tools.addWidget(self.open_log_button)
        log_layout.addLayout(log_tools)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.log_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_view.setMinimumHeight(72)
        self.log_view.setMaximumHeight(100)
        log_layout.addWidget(self.log_view)
        log_box.setMaximumHeight(158)
        root.addWidget(log_box)

        self.connect_button.clicked.connect(self._toggle_connection)
        self.send_button.clicked.connect(self._send)
        self.save_button.clicked.connect(self._save)
        self.load_button.clicked.connect(self._load)
        self.pdf_button.clicked.connect(self._export_pdf)
        self.scenario_table.currentCellChanged.connect(
            lambda row, _column, _old_row, _old_column: (
                self._select(row) if row >= 0 else None
            )
        )
        self.end_type.currentTextChanged.connect(self._end_type_changed)
        self._update_end_controls(self.end_type.currentText())

    @staticmethod
    def _number_edit(width: int) -> QLineEdit:
        widget = QLineEdit()
        widget.setFixedWidth(width)
        return widget

    def _toggle_connection(self) -> None:
        if self.connection.connected:
            self.connection.disconnect()
        else:
            self.connection.connect(self.host.text().strip(), self.port.value())

    def _set_connection_state(self, connected: bool) -> None:
        self.state_label.setText("Connected" if connected else "Disconnected")
        self.state_label.setStyleSheet("color:#087a20" if connected else "")
        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.host.setEnabled(not connected)
        self.port.setEnabled(not connected)
        self.board_state_changed.emit(connected, self.host.text().strip(), self.port.value())

    def publish_board_state(self) -> None:
        self.board_state_changed.emit(self.connection.connected, self.host.text().strip(), self.port.value())

    def toggle_board_connection(self, host: str, port: int) -> None:
        """Share the existing board connection with FC22 Tester controls."""
        if not self.connection.connected:
            self.host.setText(host)
            self.port.setValue(port)
        self._toggle_connection()

    def run_project(self) -> None:
        """Use the same commit, validation and EWS2 send path as the EmWolf tab."""
        self._send()

    def set_device_info(self, info: DeviceInfo) -> None:
        """Use identity read by WolfEye LAN status without coupling wire protocols."""
        self._live_device_info = copy.copy(info)
        self._refresh_device_info_banner()

    def _set_offline_device_model(self, model: str) -> None:
        info = self._live_device_info
        if info is not None and info.connected:
            return
        self._device_model_is_manual = True
        self.project.device = DeviceMetadata(model=model)
        self._refresh_device_info_banner()

    def _refresh_device_info_banner(self) -> None:
        info = self._live_device_info
        lan_connected = bool(info and info.connected)
        live_identity = bool(
            lan_connected
            and info
            and info.model.strip()
            and info.model not in {"—", "WolfEye"}
        )
        if live_identity and info is not None:
            self.project.device = DeviceMetadata(
                model=info.model,
                ip=info.ip,
                firmware=info.firmware,
                hardware=info.hardware,
                build=info.build,
                transport=info.transport,
            )
        device = self.project.device
        if not lan_connected and device.model not in {"FC22AR", "FC22S"}:
            device = DeviceMetadata(model=self.device_model_switch.model())
            self.project.device = device
            self._device_model_is_manual = True
        if lan_connected:
            self._device_model_is_manual = False
            self.device_model_switch.setEnabled(False)
            self.device_model_switch.setCursor(Qt.CursorShape.ArrowCursor)
            if device.model in {"FC22AR", "FC22S"}:
                self.device_model_switch.set_model(device.model)
        else:
            self.device_model_switch.setEnabled(True)
            self.device_model_switch.setCursor(Qt.CursorShape.PointingHandCursor)
            if device.model in {"FC22AR", "FC22S"}:
                self.device_model_switch.set_model(device.model)
        self.device_model_value.setText(device.model or "Not available")
        self.device_details_value.setText(
            f"FW {device.firmware or '-'}  |  HW {device.hardware or '-'}  |  "
            f"Build {device.build or '-'}"
        )
        self.device_ip_value.setText(f"IP {device.ip or '-'}")
        self.device_transport_value.setText(device.transport or "LAN status not read")
        if live_identity:
            self.device_status_value.setText("LIVE LAN")
            self.device_status_value.setStyleSheet("color:#087a20;font-weight:700")
        elif self._device_model_is_manual:
            self.device_status_value.setText("MANUAL")
            self.device_status_value.setStyleSheet("color:#a55b00;font-weight:700")
        elif device.available:
            self.device_status_value.setText("LOADED JSON")
            self.device_status_value.setStyleSheet("color:#087ad1;font-weight:700")
        else:
            self.device_status_value.setText("OFFLINE")
            self.device_status_value.setStyleSheet("color:#667784;font-weight:700")

    def _show_result(self, input_id: int, value: bool, elapsed_us: int) -> None:
        if self.execution_report is not None:
            if self.execution_report.record_transition(input_id, value, elapsed_us) is None:
                return
        self.di_labels[input_id].setText("HIGH" if value else "LOW")
        input_name = self.project.setup.digital_input_name(input_id)
        self._log(
            f"{input_name} (DI{input_id})={'HIGH' if value else 'LOW'}, "
            f"time={elapsed_us / 1000:.3f} ms"
        )

    def _record_trip(self, input_id: int, value: bool, elapsed_us: int) -> None:
        if self.execution_report is None:
            return
        scenario_index = self.execution_report.record_trip(
            input_id, value, elapsed_us
        )
        if scenario_index is None:
            return
        scenario = self.execution_report.project.scenarios[scenario_index]
        execution = self.execution_report.executions[scenario_index]
        self.test_result.emit(
            self.execution_report.project.device.model,
            emwolf_scenario_values(scenario_index, execution),
        )
        trip_time_us = execution.trip_time_us
        trip_input = execution.trip_input
        trip_value = execution.trip_value
        if trip_time_us is None or trip_input is None or trip_value is None:
            return
        input_name = self.execution_report.project.setup.digital_input_name(trip_input)
        operation = execution.operation or "TRIP"
        self._log(
            f"{scenario.name}: {operation} on {input_name} (DI{trip_input}) "
            f"({'HIGH' if trip_value else 'LOW'}), "
            f"{operation.casefold()} time={trip_time_us / 1000:.3f} ms"
        )

    def _log(self, message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {message}"
        self.log_view.appendPlainText(line)
        self.log_line.emit(line)

    def _read_setup(self) -> Setup:
        return Setup(
            {name: widget.value() for name, widget in self.offsets.items()},
            float(self.sample_time.text()),
            [
                self.di_name_edits[input_id].text().strip() or f"DI{input_id}"
                for input_id in range(1, 5)
            ],
        )

    def _load_setup(self) -> None:
        for name in CHANNEL_NAMES:
            self.offsets[name].setValue(self.project.setup.offsets[name])
        self.sample_time.setText(str(self.project.setup.sample_time_us))
        for input_id in range(1, 5):
            self.di_name_edits[input_id].setText(
                self.project.setup.digital_input_name(input_id)
            )
        self._refresh_digital_input_choices()

    def _di_name_changed(self, _input_id: int) -> None:
        if self.loading:
            return
        selected_id = self._selected_digital_input_id()
        self.project.setup.digital_input_names = [
            self.di_name_edits[input_id].text().strip() or f"DI{input_id}"
            for input_id in range(1, 5)
        ]
        self._refresh_digital_input_choices(selected_id)

    def _selected_digital_input_id(self) -> int:
        value = self.digital_input.currentData()
        return int(value) if value is not None else max(1, self.digital_input.currentIndex() + 1)

    def _refresh_digital_input_choices(self, selected_id: int | None = None) -> None:
        if selected_id is None:
            selected_id = self._selected_digital_input_id()
        self.digital_input.blockSignals(True)
        try:
            self.digital_input.clear()
            for input_id in range(1, 5):
                name = self.project.setup.digital_input_name(input_id)
                self.digital_input.addItem(f"{name} (DI{input_id})", input_id)
            selected_index = self.digital_input.findData(selected_id)
            self.digital_input.setCurrentIndex(max(0, selected_index))
        finally:
            self.digital_input.blockSignals(False)

    def _scenario_from_editor(self, existing: Scenario) -> Scenario:
        analogs: dict[str, AnalogOutput] = {}
        for channel, fields in self.analog_widgets.items():
            analogs[channel] = AnalogOutput(
                enabled=fields["enabled"].isChecked(),
                amplitude=float(fields["amplitude"].text()),
                frequency=float(fields["frequency"].text()),
                phase=int(fields["phase"].text()),
                harmonic1_order=int(fields["h1_order"].currentText()),
                harmonic1_amplitude=float(fields["h1_amplitude"].text()),
                harmonic2_order=int(fields["h2_order"].currentText()),
                harmonic2_amplitude=float(fields["h2_amplitude"].text()),
            )
        scenario = Scenario(
            self.name.text().strip() or existing.name,
            analogs,
            [widget.isChecked() for widget in self.digital_outputs],
            self.end_type.currentText(),
            self._selected_digital_input_id(),
            float(self.end_value.text()),
        )
        scenario.validate()
        return scenario

    def _commit(self, show_error: bool = True) -> bool:
        if self.current_index is None or self.loading:
            return True
        try:
            self.project.scenarios[self.current_index] = self._scenario_from_editor(
                self.project.scenarios[self.current_index]
            )
            self.project.setup = self._read_setup()
            self.project.setup.validate()
            self._update_table_row(self.current_index)
            return True
        except (ValueError, TypeError) as exc:
            if show_error:
                QMessageBox.critical(self, "Invalid value", str(exc))
            return False

    def _load_editor(self, index: int) -> None:
        self.loading = True
        try:
            scenario = self.project.scenarios[index]
            self.name.setText(scenario.name)
            self.end_type.setCurrentText(scenario.end_type)
            self._update_end_controls(scenario.end_type)
            selected_index = self.digital_input.findData(scenario.digital_input)
            self.digital_input.setCurrentIndex(max(0, selected_index))
            self.end_value.setText(str(scenario.end_value))
            for widget, value in zip(self.digital_outputs, scenario.digital_outputs):
                widget.setChecked(value)
            for channel in CHANNEL_NAMES:
                analog, fields = scenario.analogs[channel], self.analog_widgets[channel]
                fields["enabled"].setChecked(analog.enabled)
                fields["amplitude"].setText(str(analog.amplitude))
                fields["frequency"].setText(str(analog.frequency))
                fields["phase"].setText(str(analog.phase))
                fields["h1_order"].setCurrentText(str(analog.harmonic1_order))
                fields["h1_amplitude"].setText(str(analog.harmonic1_amplitude))
                fields["h2_order"].setCurrentText(str(analog.harmonic2_order))
                fields["h2_amplitude"].setText(str(analog.harmonic2_amplitude))
            self.current_index = index
        finally:
            self.loading = False

    def _select(self, index: int) -> None:
        if index == self.current_index:
            return
        if not self._commit():
            if self.current_index is not None:
                self.scenario_table.selectRow(self.current_index)
            return
        self._load_editor(index)

    def _refresh_scenarios(self, select: int | None) -> None:
        signals_were_blocked = self.scenario_table.blockSignals(True)
        try:
            self.scenario_table.setRowCount(len(self.project.scenarios))
            for row in range(len(self.project.scenarios)):
                self._update_table_row(row)
            if select is not None and self.project.scenarios:
                select = max(0, min(select, len(self.project.scenarios) - 1))
                self.scenario_table.selectRow(select)
                self._load_editor(select)
        finally:
            self.scenario_table.blockSignals(signals_were_blocked)

    def _update_table_row(self, row: int) -> None:
        scenario = self.project.scenarios[row]
        mask = (
            "".join(
                str(i + 1)
                for i, enabled in enumerate(scenario.digital_outputs)
                if enabled
            )
            or "-"
        )
        for column, value in enumerate((scenario.name, scenario.end_type, mask)):
            item = QTableWidgetItem(value)
            horizontal = (
                Qt.AlignmentFlag.AlignLeft
                if column == 0
                else Qt.AlignmentFlag.AlignCenter
            )
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | horizontal)
            self.scenario_table.setItem(row, column, item)

    def _end_type_changed(self, end_type: str) -> None:
        self._update_end_controls(end_type)
        if self.loading or self.current_index is None or end_type not in END_TYPES:
            return
        self.project.scenarios[self.current_index].end_type = end_type
        self._update_table_row(self.current_index)

    def _update_end_controls(self, end_type: str) -> None:
        capture_di = end_type == "DI_TOGGLE"
        has_value = end_type in {"CYCLES", "TIME"}
        self.digital_input_label.setVisible(capture_di)
        self.digital_input.setVisible(capture_di)
        self.end_value_label.setVisible(has_value)
        self.end_value.setVisible(has_value)
        self.end_value_label.setText("Cycles" if end_type == "CYCLES" else "Time (s)")

    def _check_scenario_limit(self) -> bool:
        if len(self.project.scenarios) < MAX_SCENARIOS:
            return True
        QMessageBox.critical(self, "Scenario limit", f"Maximum is {MAX_SCENARIOS}")
        return False

    def _add(self) -> None:
        if not self._commit() or not self._check_scenario_limit():
            return
        self.project.scenarios.append(
            Scenario(name=f"Scenario #{len(self.project.scenarios) + 1}")
        )
        self._refresh_scenarios(len(self.project.scenarios) - 1)

    def _add_default(self) -> None:
        if not self._commit() or not self._check_scenario_limit():
            return
        number = len(self.project.scenarios) + 1
        self.project.scenarios.append(
            emwolf_default_scenario(f"EmWolf default #{number}")
        )
        self._refresh_scenarios(number - 1)

    def _duplicate(self) -> None:
        if (
            self.current_index is None
            or not self._commit()
            or not self._check_scenario_limit()
        ):
            return
        item = copy.deepcopy(self.project.scenarios[self.current_index])
        item.name += " copy"
        self.project.scenarios.insert(self.current_index + 1, item)
        self._refresh_scenarios(self.current_index + 1)

    def _remove(self) -> None:
        if self.current_index is None:
            return
        index = self.current_index
        del self.project.scenarios[index]
        self.current_index = None
        self._refresh_scenarios(min(index, len(self.project.scenarios) - 1))

    def _move(self, direction: int) -> None:
        if self.current_index is None or not self._commit():
            return
        destination = self.current_index + direction
        if not 0 <= destination < len(self.project.scenarios):
            return
        (
            self.project.scenarios[self.current_index],
            self.project.scenarios[destination],
        ) = (
            self.project.scenarios[destination],
            self.project.scenarios[self.current_index],
        )
        self._refresh_scenarios(destination)

    def _send(self) -> None:
        if not self._commit():
            return
        previous_report = self.execution_report
        try:
            self.execution_report = EmWolfRunReport.begin(self.project)
            self.connection.send_project(self.project)
            self.test_run_started.emit(self.execution_report.project.device.model)
        except (ValueError, OSError, ConnectionError) as exc:
            self.execution_report = previous_report
            QMessageBox.critical(self, "Send failed", str(exc))

    @staticmethod
    def _assets_dir() -> Path:
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        return root / "assets"

    def _export_pdf(self) -> None:
        if not self._commit():
            return
        report = self.execution_report or EmWolfRunReport.begin(self.project)
        default_name = f"EmWolf-Test-Report-{datetime.now():%Y%m%d-%H%M%S}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Print EmWolf report to PDF", default_name, "PDF (*.pdf)"
        )
        if not path:
            return
        output = Path(path)
        if output.suffix.lower() != ".pdf":
            output = output.with_suffix(".pdf")
        try:
            generate_emwolf_pdf(output, report, assets_dir=self._assets_dir())
            self._log(f"PDF report saved: {output}")
            QMessageBox.information(
                self,
                "PDF report",
                f"Report saved successfully:\n{output}",
            )
        except Exception as exc:
            # ReportLab can raise several document/image exceptions. Keep a
            # failed export inside the UI instead of terminating WolfEye.
            QMessageBox.critical(self, "PDF failed", str(exc))

    def _save(self) -> None:
        if not self._commit():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save EmWolf project", "emwolf-scenarios.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            save_project(Path(path), self.project)
            self._log(f"Saved {path}")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load EmWolf project", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            project = load_project(Path(path))
            project.validate()
            self.project = project
            self._device_model_is_manual = False
            self.execution_report = None
            self.current_index = None
            self._refresh_device_info_banner()
            self._load_setup()
            self._refresh_scenarios(0)
            self._log(f"Loaded {path}")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Load failed", str(exc))

    def shutdown(self) -> None:
        self.connection.disconnect()
