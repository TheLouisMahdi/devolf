from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from wolfeye.qt import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wolfeye.config_schema import AR_MODES, BAUD_RATES, BINARY_POINT_NAMES, TCC_TYPES
from wolfeye.services.beacheye import settings_point_catalog, cycle_ar_stage
from wolfeye.numeric_schema import numeric_spec
from wolfeye.widgets.numeric_editor import configure_numeric_editor, numeric_value, set_numeric_value
from wolfeye.widgets.tcc_chart import TccChartDialog


def _get_path(root: dict[str, Any], path: str) -> Any:
    value: Any = root
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _set_path(root: dict[str, Any], path: str, new_value: Any) -> None:
    parts = path.split(".")
    value: Any = root
    for part in parts[:-1]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    if isinstance(value, list):
        value[int(parts[-1])] = new_value
    else:
        value[parts[-1]] = new_value


def _scroll_widget(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    return scroll


def _set_form_row_visible(form: QFormLayout, field: QWidget, visible: bool) -> None:
    set_row_visible = getattr(form, "setRowVisible", None)
    if set_row_visible is not None:
        set_row_visible(field, visible)
        return
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(visible)
    field.setVisible(visible)


def _fit_table_rows(table: QTableWidget) -> None:
    height = table.horizontalHeader().sizeHint().height()
    height += sum(table.rowHeight(row) for row in range(table.rowCount()))
    height += table.horizontalScrollBar().sizeHint().height()
    height += table.frameWidth() * 2
    table.setMinimumHeight(height)


def _set_numeric_editor_enabled(widget: QAbstractSpinBox, enabled: bool) -> None:
    widget.setEnabled(enabled)
    widget.setButtonSymbols(
        QAbstractSpinBox.ButtonSymbols.UpDownArrows
        if enabled
        else QAbstractSpinBox.ButtonSymbols.NoButtons
    )


class _BoundPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._bindings: dict[str, list[QWidget]] = {}

    def _bind(self, path: str, widget: QWidget) -> QWidget:
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            configure_numeric_editor(widget, path)
            widget.setMinimumWidth(116)
        self._bindings.setdefault(path, []).append(widget)
        if isinstance(widget, QCheckBox):
            widget.toggled.connect(
                lambda _value, p=path, source=widget: self._mirror_binding(p, source)
            )
        elif isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(
                lambda _value, p=path, source=widget: self._mirror_binding(p, source)
            )
        elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            widget.valueChanged.connect(
                lambda _value, p=path, source=widget: self._mirror_binding(p, source)
            )
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(
                lambda _value, p=path, source=widget: self._mirror_binding(p, source)
            )
        return widget

    @staticmethod
    def _widget_value(widget: QWidget) -> Any:
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QComboBox):
            if widget.property("bindItemData"):
                return widget.currentData()
            return widget.currentText()
        if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            return numeric_value(widget)
        if isinstance(widget, (QLineEdit, QPushButton)):
            return widget.text()
        raise TypeError(f"Unsupported bound widget: {type(widget).__name__}")

    @staticmethod
    def _set_widget_value(widget: QWidget, value: Any) -> None:
        blocked = widget.blockSignals(True)
        try:
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                if widget.property("bindItemData"):
                    index = widget.findData(value)
                    if index < 0:
                        widget.addItem(f"Unknown point (ID {value})", value)
                        index = widget.count() - 1
                    widget.setCurrentIndex(index)
                else:
                    widget.setCurrentText(str(value))
            elif isinstance(widget, QDoubleSpinBox):
                set_numeric_value(widget, float(value))
            elif isinstance(widget, QSpinBox):
                set_numeric_value(widget, int(value))
            elif isinstance(widget, (QLineEdit, QPushButton)):
                widget.setText(str(value))
        finally:
            widget.blockSignals(blocked)

    def _mirror_binding(self, path: str, source: QWidget) -> None:
        value = self._widget_value(source)
        for widget in self._bindings.get(path, ()):
            if widget is not source:
                self._set_widget_value(widget, value)

    def add_bool(self, form: QFormLayout, label: str, path: str) -> QCheckBox:
        widget = QCheckBox()
        self._bind(path, widget)
        form.addRow(label, widget)
        return widget

    def add_int(
        self,
        form: QFormLayout,
        label: str,
        path: str,
        minimum: int = 0,
        maximum: int = 65535,
        suffix: str = "",
    ) -> QSpinBox | QDoubleSpinBox:
        spec = numeric_spec(path)
        # Qt's QSpinBox is signed int32; uint32 needs a zero-decimal double.
        widget = QDoubleSpinBox() if spec and spec.maximum > 2**31 - 1 else QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setSuffix(suffix)
        self._bind(path, widget)
        form.addRow(label, widget)
        return widget

    def add_float(
        self,
        form: QFormLayout,
        label: str,
        path: str,
        minimum: float = 0.0,
        maximum: float = 9999.0,
        decimals: int = 2,
        suffix: str = "",
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setSuffix(suffix)
        widget.setSingleStep(0.01 if decimals > 1 else 0.1)
        self._bind(path, widget)
        form.addRow(label, widget)
        return widget

    def add_combo(
        self, form: QFormLayout, label: str, path: str, choices: Iterable[str]
    ) -> QComboBox:
        widget = QComboBox()
        widget.addItems([str(value) for value in choices])
        self._bind(path, widget)
        form.addRow(label, widget)
        return widget

    def add_data_combo(
        self,
        form: QFormLayout,
        label: str,
        path: str,
        choices: Iterable[tuple[int, str]],
    ) -> QComboBox:
        widget = QComboBox()
        widget.setProperty("bindItemData", True)
        for value, text in choices:
            widget.addItem(str(text), int(value))
        self._bind(path, widget)
        form.addRow(label, widget)
        return widget

    def add_text(
        self, form: QFormLayout, label: str, path: str, width: int = 160
    ) -> QLineEdit:
        widget = QLineEdit()
        widget.setMaximumWidth(width)
        self._bind(path, widget)
        form.addRow(label, widget)
        return widget

    def apply_config(self, config: dict[str, Any]) -> None:
        for path, widgets in self._bindings.items():
            value = _get_path(config, path)
            for widget in widgets:
                self._set_widget_value(widget, value)

    def update_config(self, config: dict[str, Any]) -> None:
        for path, widgets in self._bindings.items():
            if not widgets:
                continue
            value = self._widget_value(widgets[0])
            if isinstance(widgets[0], QLineEdit):
                value = str(value).strip()
            _set_path(config, path, value)

    @staticmethod
    def _section(title: str) -> tuple[QGroupBox, QFormLayout]:
        box = QGroupBox(title)
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return box, form


class GeneralPage(_BoundPage):
    """Every editable General/SCADA/I/O field exposed by the original client."""

    def __init__(self) -> None:
        super().__init__()
        self._function_operand_boxes: dict[str, list[QComboBox]] = {
            "binary": [],
            "analog": [],
        }
        self._function_row_refreshers: list[Callable[[], None]] = []
        self._point_catalog = self._load_point_catalog("FC22AR", 50)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self._measurement_tab()
        self._dnp3_tab()
        self._iec_tab()
        self._ports_tab()
        self._io_tab()
        self._system_tab()
        self._functions_tab()
        self._security_tab()

    @staticmethod
    def _load_point_catalog(
        model: str, build: int
    ) -> dict[str, tuple[tuple[int, str], ...]]:
        try:
            return settings_point_catalog(model, build)
        except (AttributeError, KeyError, OSError, RuntimeError, ValueError):
            return {"binary": (), "analog": ()}

    @staticmethod
    def _populate_operand_combo(
        combo: QComboBox, choices: Iterable[tuple[int, str]]
    ) -> None:
        selected = combo.currentData()
        blocked = combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("NOT SELECTED", 0)
            for point_id, name in choices:
                combo.addItem(str(name), int(point_id))
            index = combo.findData(selected)
            if index < 0 and selected not in (None, 0):
                combo.addItem(f"Unknown point (ID {selected})", selected)
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
        finally:
            combo.blockSignals(blocked)

    def set_device_model(self, model: str, build: int = 50) -> None:
        self._point_catalog = self._load_point_catalog(model, build)
        for kind, combos in self._function_operand_boxes.items():
            for combo in combos:
                self._populate_operand_combo(combo, self._point_catalog[kind])

    def apply_config(self, config: dict[str, Any]) -> None:
        super().apply_config(config)
        for refresh in self._function_row_refreshers:
            refresh()

    def _new_grid_tab(self, title: str) -> QGridLayout:
        content = QWidget()
        grid = QGridLayout(content)
        grid.setAlignment(grid.alignment())
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(99, 1)
        self.tabs.addTab(_scroll_widget(content), title)
        return grid

    def _measurement_tab(self) -> None:
        grid = self._new_grid_tab("Measurement")
        box, form = self._section("Rated Values")
        self.add_combo(
            form, "Frequency", "general.measurement.frequency_hz", ("50", "60")
        )
        self.add_int(
            form, "Voltage", "general.measurement.rated_voltage_v", 0, 99900, " V"
        )
        self.add_combo(
            form, "Source Side", "general.measurement.source_side", ("ABC", "RST")
        )
        self.add_combo(
            form, "Phase Rotation", "general.measurement.phase_rotation", ("ABC", "ACB", "BCA", "CAB", "BAC", "CBA")
        )
        self.add_float(form, "LSD Level", "general.system.lsd_level", 0.5, 6.0, 1)
        grid.addWidget(box, 0, 0)

        box, form = self._section("Current Coefficients")
        for label, name in (
            ("Line A", "line_a"),
            ("Line B", "line_b"),
            ("Line C", "line_c"),
            ("Residual", "residual"),
        ):
            self.add_int(
                form, label, f"general.measurement.coefficients.{name}", 1, 9999
            )
        grid.addWidget(box, 0, 1)

        box, form = self._section("Deadbands")
        specs = (
            ("Voltages", "voltages_v", "float", 0.1, 65.0, " kV"),
            ("Phase Currents", "phase_currents_a", "int", 1, 99, " A"),
            ("Residual Currents", "residual_currents_a", "int", 1, 99, " A"),
            ("Battery Voltage", "battery_voltage_v", "float", 1.0, 10.0, " V"),
            ("Power Factor", "power_factor_pct", "int", 5, 99, " %"),
            ("Frequency", "frequency_hz", "float", 0.0, 99.9, " Hz"),
            ("Powers", "powers", "int", 1000, 9999, ""),
            ("Counters", "counters", "int", 1, 9999, ""),
        )
        for label, name, kind, low, high, suffix in specs:
            path = f"general.measurement.deadbands.{name}"
            if kind == "int":
                self.add_int(form, label, path, int(low), int(high), suffix)
            else:
                self.add_float(form, label, path, float(low), float(high), 1, suffix)
        grid.addWidget(box, 1, 0, 1, 2)

        box, form = self._section("SCADA")
        self.add_bool(form, "Enabled", "general.scada.enabled")
        self.add_combo(form, "Protocol", "general.scada.protocol", ("DNP3", "IEC"))
        self.add_combo(
            form,
            "Data Port",
            "general.scada.data_port",
            ("ETHERNET", "RS232", "RS485", "MODEM"),
        )
        grid.addWidget(box, 2, 0, 1, 2)

    def _dnp3_tab(self) -> None:
        grid = self._new_grid_tab("DNP3")
        box, form = self._section("Link")
        p = "general.scada.dnp3.link"
        self.add_int(form, "Slave Address", f"{p}.slave_address", 0, 65534)
        self.add_int(form, "Master Address", f"{p}.master_address", 0, 65534)
        self.add_int(form, "Confirm Retry", f"{p}.confirm_retry", 0, 32767)
        self.add_float(
            form, "Confirm Timeout", f"{p}.confirm_timeout_s", 1, 255, 2, " s"
        )
        self.add_float(form, "Keep Alive", f"{p}.keep_alive_s", 60, 9999, 2, " s")
        self.add_bool(form, "Confirm User Data", f"{p}.confirm_user_data")
        self.add_bool(form, "Keep Alive Enable", f"{p}.keep_alive_enabled")
        grid.addWidget(box, 0, 0)

        box, form = self._section("Application")
        p = "general.scada.dnp3.application"
        self.add_int(form, "Cold Restart Delay", f"{p}.cold_restart_delay")
        self.add_int(form, "Warm Restart Delay", f"{p}.warm_restart_delay")
        self.add_float(
            form,
            "Solicited Confirm Timeout",
            f"{p}.solicited_confirm_timeout_s",
            1,
            255,
            2,
            " s",
        )
        self.add_float(form, "Select Timeout", f"{p}.select_timeout_s", 1, 255, 2, " s")
        grid.addWidget(box, 0, 1)

        box, form = self._section("Unsolicited")
        p = "general.scada.dnp3.unsolicited"
        self.add_bool(form, "Enable Unsolicited", f"{p}.enabled")
        for number in range(1, 4):
            self.add_bool(form, f"Enable Class {number}", f"{p}.class_{number}")
        unused_buffer = self.add_int(form, "Max Event Buffer", f"{p}.max_event_buffer", 1, 99)
        unused_buffer.setEnabled(False)
        unused_buffer.setToolTip("Not used or serialized by the company settings ABI.")
        self.add_int(form, "Hold Time", f"{p}.hold_time_s", 0, 10, " s")
        grid.addWidget(box, 1, 0)

        box, form = self._section("Time Synchronization")
        p = "general.scada.dnp3.time_sync"
        self.add_bool(form, "Enable", f"{p}.enabled")
        self.add_float(
            form, "Request Time Interval", f"{p}.request_interval_s", 300, 9999, 2, " s"
        )
        grid.addWidget(box, 1, 1)

        box, form = self._section("Mapping")
        p = "general.scada.dnp3.mapping"
        mappings = (
            ("Static Binary Input", "static_binary_input", ("G1V1", "G1V2")),
            ("Event Binary Input", "event_binary_input", ("G2V1", "G2V2", "G2V3")),
            (
                "Static Analog Input",
                "static_analog_input",
                tuple(f"G30V{i}" for i in range(1, 7)),
            ),
            (
                "Event Analog Input",
                "event_analog_input",
                tuple(f"G32V{i}" for i in range(1, 9)),
            ),
            ("Event Double Binary", "event_double_binary", ("G4V1", "G4V2", "G4V3")),
            ("Event Binary Output", "event_binary_output", ("G11V1", "G11V2")),
            (
                "Static Analog Output",
                "static_analog_output",
                tuple(f"G40V{i}" for i in range(1, 5)),
            ),
            (
                "Event Analog Output",
                "event_analog_output",
                tuple(f"G42V{i}" for i in range(1, 9)),
            ),
            ("Static Counter", "static_counter", ("G20V1", "G20V2", "G20V5", "G20V6")),
            ("Event Counter", "event_counter", ("G22V1", "G22V2", "G22V5", "G22V6")),
        )
        for label, name, values in mappings:
            self.add_combo(form, label, f"{p}.{name}", values)
        grid.addWidget(box, 2, 0, 1, 2)

    def _iec_tab(self) -> None:
        grid = self._new_grid_tab("IEC")
        box, form = self._section("General")
        p = "general.scada.iec.general"
        self.add_combo(form, "ASDU Address Size", f"{p}.asdu_address_size", ("1", "2"))
        self.add_int(form, "ASDU Address", f"{p}.asdu_address")
        self.add_combo(form, "IOA Size", f"{p}.ioa_size", ("1", "2", "3"))
        self.add_combo(form, "COT Size", f"{p}.cot_size", ("1", "2"))
        self.add_int(form, "Originator Address", f"{p}.originator_address")
        self.add_bool(form, "ACTTERM", f"{p}.actterm")
        self.add_bool(form, "Time Synchronization", f"{p}.time_sync")
        grid.addWidget(box, 0, 0)

        box, form = self._section("Base Addresses")
        p = "general.scada.iec.base_addresses"
        for label, name in (
            ("Single Status", "single_status"),
            ("Double Status", "double_status"),
            ("Measured Values", "measured_values"),
            ("Integrated Total", "integrated_total"),
            ("Single Command", "single_command"),
            ("Double Command", "double_command"),
            ("Set Point Command", "set_point_command"),
            ("Parameter Command", "parameter_command"),
        ):
            self.add_int(form, label, f"{p}.{name}")
        grid.addWidget(box, 0, 1)

        box, form = self._section("IEC 101")
        p = "general.scada.iec.iec101"
        self.add_combo(form, "Link Address Size", f"{p}.link_address_size", ("1", "2"))
        self.add_int(form, "Link Address", f"{p}.link_address")
        self.add_combo(
            form, "Channel Mode", f"{p}.channel_mode", ("BALANCED", "UNBALANCED")
        )
        self.add_float(form, "ACK Timeout", f"{p}.ack_timeout_s", 1, 255, 2, " s")
        self.add_float(form, "Repeat Timeout", f"{p}.repeat_timeout_s", 1, 255, 2, " s")
        self.add_int(form, "Channel Retry", f"{p}.channel_retry")
        self.add_float(form, "RX Timeout", f"{p}.rx_timeout_s", 1, 255, 2, " s")
        self.add_bool(form, "Single Character ACK", f"{p}.single_char_ack")
        grid.addWidget(box, 1, 0)

        box, form = self._section("IEC 104")
        p = "general.scada.iec.iec104"
        for number in range(4):
            self.add_float(
                form, f"Timeout {number}", f"{p}.timeout_{number}_s", 1, 255, 2, " s"
            )
        self.add_int(form, "K", f"{p}.k")
        self.add_int(form, "W", f"{p}.w")
        grid.addWidget(box, 1, 1)

    def _serial_section(self, title: str, path: str) -> QGroupBox:
        box, form = self._section(title)
        self.add_combo(form, "Baudrate", f"{path}.baudrate", BAUD_RATES)
        self.add_combo(form, "Parity", f"{path}.parity", ("NONE", "ODD", "EVEN"))
        self.add_combo(form, "Stop Bits", f"{path}.stop_bits", ("1", "2"))
        self.add_combo(form, "Data Bits", f"{path}.data_bits", ("7", "8"))
        return box

    def _ports_tab(self) -> None:
        grid = self._new_grid_tab("Ports")
        grid.addWidget(self._serial_section("RS485", "general.scada.ports.rs485"), 0, 0)
        grid.addWidget(self._serial_section("RS232", "general.scada.ports.rs232"), 0, 1)
        box, form = self._section("Ethernet Transport")
        p = "general.scada.ports.ethernet"
        self.add_combo(form, "Mode", f"{p}.mode", ("SERVER", "CLIENT"))
        self.add_int(form, "Local Port", f"{p}.local_port", 0, 65535)
        self.add_int(form, "Remote Port", f"{p}.remote_port", 0, 65535)
        self.add_text(form, "Remote IP", f"{p}.remote_ip")
        grid.addWidget(box, 1, 0)
        box, form = self._section("Modem")
        p = "general.scada.ports.modem"
        apn = self.add_text(form, "APN Name", f"{p}.apn")
        apn.setMaxLength(15)
        self.add_combo(form, "Network", f"{p}.network", ("AUTO", "GSM", "LTE"))
        self.add_combo(form, "Baudrate", f"{p}.baudrate", BAUD_RATES)
        self.add_combo(form, "Mode", f"{p}.mode", ("SERVER", "CLIENT"))
        self.add_int(form, "Local Port", f"{p}.local_port", 0, 65535)
        self.add_int(form, "Remote Port", f"{p}.remote_port", 0, 65535)
        self.add_text(form, "Remote IP", f"{p}.remote_ip")
        grid.addWidget(box, 1, 1)

    def _io_tab(self) -> None:
        grid = self._new_grid_tab("I/O")
        box, form = self._section("Open / Close")
        p = "general.io.open_close"
        self.add_combo(
            form, "Open Read Mode", f"{p}.open_read_mode", ("SINGLE", "DOUBLE")
        )
        self.add_combo(
            form, "Close Read Mode", f"{p}.close_read_mode", ("SINGLE", "DOUBLE")
        )
        self.add_bool(form, "Open Need Confirm", f"{p}.open_need_confirm")
        self.add_bool(form, "Close Need Confirm", f"{p}.close_need_confirm")
        grid.addWidget(box, 0, 0)

        box, form = self._section("Ethernet")
        p = "general.io.ethernet"
        self.add_bool(form, "DHCP", f"{p}.dhcp")
        self.add_text(form, "IP", f"{p}.ip")
        self.add_text(form, "Subnet Mask", f"{p}.subnet_mask")
        self.add_text(form, "Gateway", f"{p}.gateway")
        grid.addWidget(box, 0, 1)

        box, form = self._section("Digital Inputs")
        p = "general.io.digital_inputs"
        self.add_bool(form, "Chatter Enabled", f"{p}.chatter_enabled")
        self.add_float(
            form, "Chatter Reset Time", f"{p}.chatter_reset_s", 5, 60, 3, " s"
        )
        self.add_float(
            form, "Validation Time", f"{p}.validation_time_s", 0.002, 0.128, 3, " s"
        )
        for index in range(7):
            self.add_combo(
                form,
                f"Input {index + 1}",
                f"{p}.inputs.{index}",
                ("DISABLE", "HIGH STATE", "LOW STATE"),
            )
        grid.addWidget(box, 1, 0)

        outputs = QGroupBox("Digital Outputs")
        table = QTableWidget(7, 6, outputs)
        table.setHorizontalHeaderLabels(
            ("Output", "If", "Get", "Recogn. (s)", "Then", "Pulse (s)")
        )
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((55, 120, 68, 82, 86, 82)):
            table.setColumnWidth(column, width)
        layout = QVBoxLayout(outputs)
        layout.addWidget(table)
        for index in range(7):
            table.setItem(index, 0, QTableWidgetItem(f"DO{index + 1}"))
            when = QComboBox()
            when.setProperty("bindItemData", True)
            self._populate_operand_combo(when, self._point_catalog["binary"])
            self._function_operand_boxes["binary"].append(when)
            active = QComboBox()
            active.addItems(("FALSE", "TRUE"))
            recognition = QDoubleSpinBox()
            recognition.setRange(0.01, 120)
            recognition.setDecimals(3)
            recognition.setSuffix(" s")
            status = QComboBox()
            status.addItems(("DISABLE", "LATCH ON", "PULSE ON"))
            pulse = QDoubleSpinBox()
            pulse.setRange(0.01, 120)
            pulse.setDecimals(3)
            pulse.setSuffix(" s")
            for column, widget in enumerate(
                (when, active, recognition, status, pulse), 1
            ):
                widget.setStyleSheet("min-width: 0px;")
                table.setCellWidget(index, column, widget)
            base = f"general.io.digital_outputs.{index}"
            self._bind(f"{base}.when", when)
            self._bind(f"{base}.is", active)
            self._bind(f"{base}.recognition_s", recognition)
            self._bind(f"{base}.then", status)
            self._bind(f"{base}.for_s", pulse)
            status.currentTextChanged.connect(
                lambda value, target=pulse: target.setEnabled(value == "PULSE ON")
            )
        grid.addWidget(outputs, 1, 1)

        indicators = QGroupBox("Indicators")
        table = QTableWidget(6, 4, indicators)
        table.setHorizontalHeaderLabels(("LED", "When", "Is", "Then"))
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout = QVBoxLayout(indicators)
        layout.addWidget(table)
        for index in range(6):
            table.setItem(index, 0, QTableWidgetItem(f"LED{index + 1}"))
            when = QComboBox()
            when.addItems(BINARY_POINT_NAMES)
            active = QComboBox()
            active.addItems(("FALSE", "TRUE"))
            status = QComboBox()
            status.addItems(("DISABLE", "ON", "BLINK"))
            for column, widget in enumerate((when, active, status), 1):
                table.setCellWidget(index, column, widget)
            base = f"general.io.indicators.{index}"
            self._bind(f"{base}.when", when)
            self._bind(f"{base}.is", active)
            self._bind(f"{base}.then", status)
        _fit_table_rows(table)
        grid.addWidget(indicators, 2, 0, 1, 2)

    def _security_tab(self) -> None:
        grid = self._new_grid_tab("Security & Heater")
        box, form = self._section("Heater")
        self.add_bool(form, "Enable", "general.heater.enabled")
        self.add_int(
            form, "On Temperature", "general.heater.on_temperature_c", 0, 60, " °C"
        )
        self.add_int(
            form, "Off Temperature", "general.heater.off_temperature_c", 0, 60, " °C"
        )
        grid.addWidget(box, 0, 0)
        box, form = self._section("Security")
        p = "general.security"
        self.add_bool(form, "TLS", f"{p}.tls")
        self.add_bool(form, "Web Security", f"{p}.web")
        self.add_int(form, "Password", f"{p}.password", 0, 65535)
        self.add_bool(form, "Default Certificate", f"{p}.default_certificate")
        for index in range(4):
            self.add_text(
                form, f"Allowed Remote IP {index + 1}", f"{p}.remote_ips.{index}"
            )
        grid.addWidget(box, 0, 1)

    def _system_tab(self) -> None:
        grid = self._new_grid_tab("System")
        box, form = self._section("Fault Locator")
        p = "general.system.fault_locator"
        self.add_bool(form, "Enable", f"{p}.enabled")
        for label, name in (("R0", "r0"), ("X0", "x0"), ("R1", "r1"), ("X1", "x1")):
            self.add_float(form, label, f"{p}.{name}", 0.001, 50.0, 3)
        self.add_float(
            form, "Length of Line", f"{p}.line_length_km", 0.01, 30.0, 2, " km"
        )
        grid.addWidget(box, 0, 0)

        box, form = self._section("Synchronization - General")
        p = "general.system.synchronization"
        self.add_bool(form, "Enable", f"{p}.enabled")
        self.add_combo(
            form,
            "Phase Selection",
            f"{p}.phase_selection",
            ("PHASE TO GROUND", "PHASE TO PHASE"),
        )
        self.add_combo(
            form, "Bus and Line", f"{p}.bus_and_line", ("ABC/RST", "RST/ABC")
        )
        self.add_combo(
            form,
            "Live/Dead Autoreclose",
            f"{p}.live_dead_autoreclose",
            ("DISABLE", "LIVE BUS", "LIVE LINE", "LIVE/DEAD"),
        )
        self.add_bool(form, "DLDB Autoreclose", f"{p}.dldb_autoreclose")
        self.add_combo(
            form,
            "Live/Dead Manual Close",
            f"{p}.live_dead_manual_close",
            ("DISABLE", "LIVE BUS", "LIVE LINE", "LIVE/DEAD"),
        )
        self.add_bool(form, "DLDB Manual Close", f"{p}.dldb_manual_close")
        for label, name, low, high in (
            ("Live Bus Voltage Multiplier", "live_bus_voltage_multiplier", 0.3, 1.2),
            ("Live Line Voltage Multiplier", "live_line_voltage_multiplier", 0.3, 1.2),
            ("Bus Max Voltage Multiplier", "bus_max_voltage_multiplier", 0.8, 1.4),
            ("Line Max Voltage Multiplier", "line_max_voltage_multiplier", 0.8, 1.4),
            ("Voltage Difference Multiplier", "voltage_difference_multiplier", 0.03, 0.5),
        ):
            self.add_float(form, label, f"{p}.{name}", low, high, 2)
        grid.addWidget(box, 0, 1)

        box, form = self._section("Synchronism")
        self.add_bool(form, "Enable for Recloser", f"{p}.sync_enabled_for_recloser")
        self.add_float(
            form, "Max Slip Frequency", f"{p}.max_slip_frequency_hz", 0.03, 0.1, 2, " Hz"
        )
        self.add_int(
            form,
            "Phase Angle Difference",
            f"{p}.phase_angle_difference_deg",
            0,
            90,
            " °",
        )
        self.add_float(
            form, "Manual Pre-Sync Time", f"{p}.manual_pre_sync_s", 0, 60, 2, " s"
        )
        grid.addWidget(box, 1, 0)

        box, form = self._section("Auto Synchroniser")
        self.add_int(
            form,
            "Fundamental Frequency",
            f"{p}.fundamental_frequency_hz",
            47,
            64,
            " Hz",
        )
        for label, name, low, high, suffix in (
            ("Max Frequency Deviation", "max_frequency_deviation_hz", 0, 1, " Hz"),
            ("Max Slip", "auto_max_slip_hz", 0.03, 0.5, " Hz"),
            ("Max ROC Slip", "max_roc_slip_hz_s", 0.01, 1, " Hz/s"),
        ):
            self.add_float(form, label, f"{p}.{name}", low, high, 2, suffix)
        self.add_float(form, "Waiting Time", f"{p}.waiting_time_s", 100, 3600, 2, " s")
        self.add_bool(form, "Anti-Motoring", f"{p}.anti_motoring_s")
        grid.addWidget(box, 1, 1)

    def _functions_tab(self) -> None:
        container = QTabWidget()
        self.function_tabs = container
        for index in range(16):
            content = QWidget()
            form = QFormLayout(content)
            p = f"general.system.functions.{index}"
            self.add_bool(form, "Enabled", f"{p}.enabled")
            value_type = self.add_combo(
                form, "Value Type", f"{p}.value_type", ("BINARY", "ANALOG")
            )
            binary_operator = self.add_combo(
                form,
                "Binary Operator",
                f"{p}.operator",
                ("OR", "AND", "EQUAL"),
            )
            binary_operands: list[QComboBox] = []
            for label, name in (
                ("Binary Value A", "value_a"),
                ("Binary Value B", "value_b"),
                ("Binary Value C", "value_c"),
            ):
                operand = self.add_data_combo(
                    form,
                    label,
                    f"{p}.{name}",
                    ((0, "NOT SELECTED"), *self._point_catalog["binary"]),
                )
                binary_operands.append(operand)
                self._function_operand_boxes["binary"].append(operand)
            compared_to = self.add_combo(
                form, "Compared To", f"{p}.compared_to", ("FALSE", "TRUE")
            )
            analog_operator = self.add_combo(
                form,
                "Analog Operator",
                f"{p}.analog_operator",
                ("GREATER", "LESS"),
            )
            analog_operand = self.add_data_combo(
                form,
                "Analog Value A",
                f"{p}.analog_value_a",
                ((0, "NOT SELECTED"), *self._point_catalog["analog"]),
            )
            self._function_operand_boxes["analog"].append(analog_operand)
            analog_value = self.add_int(
                form,
                "Analog Compared To",
                f"{p}.analog_compared_to",
                0,
                9_999_999,
            )
            self.add_float(form, "Time", f"{p}.time_s", 0, 10, 3, " s")
            self.add_combo(
                form,
                "Action",
                f"{p}.action",
                ("NOTHING", "OPEN", "CLOSE"),
            )

            def refresh_rows(
                _value: str = "",
                *,
                form: QFormLayout = form,
                value_type: QComboBox = value_type,
                binary_operator: QComboBox = binary_operator,
                binary_operands: list[QComboBox] = binary_operands,
                compared_to: QComboBox = compared_to,
                analog_operator: QComboBox = analog_operator,
                analog_operand: QComboBox = analog_operand,
                analog_value: QSpinBox = analog_value,
            ) -> None:
                is_binary = value_type.currentText() == "BINARY"
                is_equal = binary_operator.currentText() == "EQUAL"
                _set_form_row_visible(form, binary_operator, is_binary)
                _set_form_row_visible(form, binary_operands[0], is_binary)
                _set_form_row_visible(form, binary_operands[1], is_binary and not is_equal)
                _set_form_row_visible(form, binary_operands[2], is_binary and not is_equal)
                _set_form_row_visible(form, compared_to, is_binary and is_equal)
                _set_form_row_visible(form, analog_operator, not is_binary)
                _set_form_row_visible(form, analog_operand, not is_binary)
                _set_form_row_visible(form, analog_value, not is_binary)

            value_type.currentTextChanged.connect(refresh_rows)
            binary_operator.currentTextChanged.connect(refresh_rows)
            self._function_row_refreshers.append(refresh_rows)
            refresh_rows()
            container.addTab(_scroll_widget(content), f"Function {index + 1}")
        self.tabs.addTab(container, "Functions")


class ProtectionPage(_BoundPage):
    ELEMENT_NAMES = (
        "Delayed +",
        "Fast Trip +",
        "Highset +",
        "Delayed -",
        "Fast Trip -",
        "Highset -",
    )

    def __init__(self) -> None:
        super().__init__()
        self._config: dict[str, Any] | None = None
        self._device_model = "FC22AR"
        self._global_widgets: dict[str, QCheckBox] = {}
        self._feature_widgets: dict[str, QCheckBox] = {}
        self._group_tabs: list[QTabWidget] = []
        self._master_extension_tabs: list[QTabWidget] = []
        self._tcc_field_refreshers: list[tuple[QComboBox, Callable[[str], None]]] = []
        self._chart_dialogs: set[TccChartDialog] = set()
        root = QVBoxLayout(self)
        general = QGroupBox("Protection")
        row = QGridLayout(general)
        self.group_select = QComboBox()
        self.group_select.addItems(("Group 1", "Group 2", "Group 3", "Group 4"))
        row.addWidget(QLabel("Selected Group"), 0, 0)
        row.addWidget(self.group_select, 0, 1)
        self.device_badge = QLabel("AUTO RECLOSER · FC22AR")
        self.device_badge.setObjectName("protectionDeviceBadge")
        row.addWidget(self.device_badge, 1, 0, 1, 2)
        toggles = (
            ("Protection", "enabled"),
            ("Enable OC", "oc_enabled"),
            ("Enable EF", "ef_enabled"),
            ("Enable SEF", "sef_enabled"),
            ("Enable CLP", "clp_enabled"),
            ("Enable IR", "inrush_enabled"),
            ("Frequency Protection", "frequency_enabled"),
            ("Voltage Protection", "voltage_enabled"),
            ("Live Line", "live_line_enabled"),
        )
        for index, (label, name) in enumerate(toggles):
            widget = QCheckBox(label)
            self._bind(f"protection.{name}", widget)
            self._global_widgets[name] = widget
            row.addWidget(widget, index // 6, index % 6 + 2)
        master_flags = (
            "NPS",
            "Admittance",
            "Over Voltage",
            "Over Frequency",
            "Harmonic",
            "ABR",
            "Alarm Mode",
            "Hot Line Tag",
            "LL Link To HLT",
            "UV4 Sag",
            "OV3",
            "ROCOF",
            "VVS",
            "PDOP",
            "PDUP",
            "DFT",
            "SSM",
            "Harmonic IR Blocking",
            "Logical Block Close",
            "LLB",
            "Sectionalizer",
            "Breaker",
        )
        for index, label in enumerate(master_flags):
            name = label.lower().replace(" ", "_")
            widget = QCheckBox(label)
            self._bind(f"protection.feature_flags.{name}", widget)
            self._feature_widgets[name] = widget
            row.addWidget(widget, 2 + index // 7, index % 7)
        sectionalizer = self._feature_widgets["sectionalizer"]
        breaker = self._feature_widgets["breaker"]
        sectionalizer.toggled.connect(
            lambda checked: breaker.setChecked(False) if checked else None
        )
        breaker.toggled.connect(
            lambda checked: sectionalizer.setChecked(False) if checked else None
        )
        root.addWidget(general)

        self.group_stack = QStackedWidget()
        root.addWidget(self.group_stack, 1)
        for index in range(4):
            self.group_stack.addWidget(self._build_group(index))
        self.group_select.currentIndexChanged.connect(self.group_stack.setCurrentIndex)
        self.set_device_model(self._device_model)

    def _build_group(self, group_index: int) -> QWidget:
        tabs = QTabWidget()
        base = f"protection.groups.{group_index}"
        tabs.addTab(self._ocef_tab(base), "OCEF / TCC")
        tabs.addTab(self._nps_tab(base), "NPS")
        tabs.addTab(self._sef_tab(base), "SEF / Reclosing")
        tabs.addTab(self._auxiliary_tab(base), "Auxiliary")
        tabs.addTab(self._voltage_tab(base), "Voltage / Frequency / ABR")
        tabs.addTab(self._master_extensions_tab(base), "Master Extensions")
        tabs.addTab(self._sectionalizer_protection_tab(base), "Protection")
        tabs.addTab(self._sectionalizer_master(base), "Sectionalizing / Breaker")
        tabs.addTab(self._sectionalizer_voltage_tab(base), "Voltage / BC46")
        self._group_tabs.append(tabs)
        return tabs

    def _nps_tab(self, base: str) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(
            self._element_table(
                "Negative Phase Sequence (NPS)", f"{base}.nps", self.ELEMENT_NAMES
            )
        )
        box, form = self._section("Directional NPS")
        self.add_int(form, "Torque Angle", f"{base}.nps.torque_angle_deg", 0, 359, " °")
        layout.addWidget(box)
        layout.addStretch()
        return _scroll_widget(content)

    def _master_extensions_tab(self, base: str) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._directional_master(base), "Directional / Yn")
        tabs.addTab(self._quality_master(base), "Overload / IR")
        tabs.addTab(self._voltage_master(base), "Voltage / AR")
        tabs.addTab(self._harmonic_master(base), "Frequency / Harmonic")
        tabs.addTab(self._sectionalizer_master(base), "Sectionalizer")
        self._master_extension_tabs.append(tabs)
        return tabs

    def _element_table(
        self, title: str, path: str, names: tuple[str, ...]
    ) -> QGroupBox:
        box = QGroupBox(title)
        is_sef = all(name.startswith("SEF") for name in names)
        headers = (
            "Element",
            "On",
            "TCC Type",
            "Pickup A",
            "TM",
            "Min I",
            "Tmin s",
            "Trip s",
            "Tmax s",
            "Adder s",
            "Reset s",
            "Max",
            "Max I",
            "AR1",
            "AR2",
            "AR3",
            "AR4",
        )
        table = QTableWidget(len(names), len(headers))
        table.setObjectName("tccElementTable")
        # The global form style gives spin boxes a wide minimum that is useful
        # in forms but makes cell widgets overflow into the next TCC column.
        # Override only that minimum here; the table still controls cell width.
        table.setStyleSheet("""
        QSpinBox, QDoubleSpinBox {
            min-width: 0px;
            padding: 2px 20px 2px 6px;
        }

        QSpinBox::up-button, QDoubleSpinBox::up-button {
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 16px;
        }

        QSpinBox::down-button, QDoubleSpinBox::down-button {
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 16px;
        }
        """)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        table.horizontalHeader().setMinimumSectionSize(55)
        table.setMinimumHeight(235 if len(names) > 2 else 125)
        table.setColumnWidth(0, 90)
        table.setColumnWidth(2, 95)
        for column in range(3, 12):
            table.setColumnWidth(column, 120)
        for row, name in enumerate(names):
            open_curve = QPushButton(name)
            open_curve.setObjectName("tccElementButton")
            open_curve.setToolTip("Open the company TCC protection curve")
            open_curve.clicked.connect(
                lambda _checked=False, selected=row: self._open_tcc_dialog(
                    title, path, names, selected
                )
            )
            table.setCellWidget(row, 0, open_curve)
            base = f"{path}.elements.{row}"
            highset = len(names) > 2 and (row + 1) % 3 == 0
            fast_trip = len(names) > 2 and row % 3 == 1
            enabled = QCheckBox()
            curve = QComboBox()
            curve.addItems(TCC_TYPES)
            pickup = QSpinBox()
            if is_sef:
                pickup.setRange(1, 80)
            elif highset:
                pickup.setRange(20, 6000)
            else:
                pickup.setRange(10, 1280)
            tm = self._table_float(0.01, 15)
            minimum = self._table_float(1, 5)
            tmin = self._table_float(0, 10)
            trip = self._table_float(0, 2 if highset else 120)
            tmax = self._table_float(1, 120)
            adder = self._table_float(0, 2)
            reset = self._table_float(0, 2)
            max_mode = QCheckBox()
            max_current = self._table_float(1.1, 10.0)
            widgets: list[QWidget] = [
                enabled,
                curve,
                pickup,
                tm,
                minimum,
                tmin,
                trip,
                tmax,
                adder,
                reset,
                max_mode,
                max_current,
            ]
            paths = (
                "enabled",
                "type",
                "pickup_a",
                "time_multiplier",
                "min_current_multiplier",
                "definite_min_time_s",
                "tripping_time_s",
                "max_tripping_time_s",
                "time_adder_s",
                "reset_time_s",
                "max_mode",
                "max_current_multiplier",
            )
            for stage in range(4):
                mode = QPushButton(AR_MODES[0])
                mode.clicked.connect(
                    lambda _checked=False, r=row, s=stage, p=path, sef=is_sef:
                    self._cycle_ar_stage(p, r, s, sef)
                )
                widgets.append(mode)
                paths += (f"ar_modes.{stage}",)
            for column, (widget, subpath) in enumerate(zip(widgets, paths), 1):
                table.setCellWidget(row, column, widget)
                self._bind(f"{base}.{subpath}", widget)
            def update_tcc_fields(
                curve_name: str,
                *,
                is_highset: bool = highset,
                curve_widget: QComboBox = curve,
                tm_widget: QDoubleSpinBox = tm,
                minimum_widget: QDoubleSpinBox = minimum,
                tmin_widget: QDoubleSpinBox = tmin,
                trip_widget: QDoubleSpinBox = trip,
                tmax_widget: QDoubleSpinBox = tmax,
                adder_widget: QDoubleSpinBox = adder,
                reset_widget: QDoubleSpinBox = reset,
                max_widget: QCheckBox = max_mode,
                max_current_widget: QDoubleSpinBox = max_current,
                is_sef_element: bool = is_sef,
                is_fast_trip_element: bool = fast_trip,
            ) -> None:
                if is_sef_element:
                    curve_widget.setEnabled(False)
                    for target in (
                        tm_widget,
                        minimum_widget,
                        tmin_widget,
                        tmax_widget,
                        adder_widget,
                    ):
                        _set_numeric_editor_enabled(target, False)
                    _set_numeric_editor_enabled(trip_widget, True)
                    _set_numeric_editor_enabled(reset_widget, True)
                    max_widget.setEnabled(False)
                    _set_numeric_editor_enabled(max_current_widget, False)
                    return
                definite_time = curve_name == "TD"
                inverse_time = not is_highset and not definite_time
                curve_widget.setEnabled(not is_highset)
                for target in (
                    tm_widget,
                    minimum_widget,
                    tmin_widget,
                    tmax_widget,
                    adder_widget,
                ):
                    _set_numeric_editor_enabled(target, inverse_time)
                _set_numeric_editor_enabled(
                    trip_widget, is_highset or definite_time
                )
                _set_numeric_editor_enabled(
                    reset_widget,
                    not is_highset
                    and (definite_time or curve_name.startswith("IEC ")),
                )
                supports_maximum = is_fast_trip_element and inverse_time
                max_widget.setEnabled(supports_maximum)
                _set_numeric_editor_enabled(
                    max_current_widget,
                    supports_maximum and max_widget.isChecked(),
                )

            curve.currentTextChanged.connect(update_tcc_fields)
            max_mode.toggled.connect(
                lambda _checked, curve_widget=curve, refresh=update_tcc_fields: refresh(
                    curve_widget.currentText()
                )
            )
            self._tcc_field_refreshers.append((curve, update_tcc_fields))
            update_tcc_fields(curve.currentText())
        layout = QVBoxLayout(box)
        layout.addWidget(table)
        return box

    def _cycle_ar_stage(self, path: str, row: int, stage: int, sef: bool) -> None:
        first = row if sef else (row // 3) * 3
        rows = 1 if sef else 3
        buttons = [self._bindings[f"{path}.elements.{r}.ar_modes.{s}"][0]
                   for r in range(first, first + rows) for s in range(4)]
        values, blocked = cycle_ar_stage(
            [AR_MODES.index(button.text()) for button in buttons],
            [not button.isEnabled() for button in buttons], row - first, stage, sef,
        )
        for button, value, disabled in zip(buttons, values, blocked):
            button.setText(AR_MODES[value])
            button.setEnabled(not disabled)

    @staticmethod
    def _table_float(minimum: float, maximum: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(2)
        widget.setSingleStep(0.01)
        return widget

    def _ocef_tab(self, base: str) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(
            self._element_table(
                "Phase Overcurrent (OC)", f"{base}.oc", self.ELEMENT_NAMES
            )
        )
        torque = QHBoxLayout()
        torque.addWidget(QLabel("OC Torque Angle"))
        oc_at = QSpinBox()
        oc_at.setRange(0, 359)
        oc_at.setSuffix(" °")
        self._bind(f"{base}.oc.torque_angle_deg", oc_at)
        torque.addWidget(oc_at)
        torque.addSpacing(20)
        torque.addWidget(QLabel("EF Torque Angle"))
        ef_at = QSpinBox()
        ef_at.setRange(0, 359)
        ef_at.setSuffix(" °")
        self._bind(f"{base}.ef.torque_angle_deg", ef_at)
        torque.addWidget(ef_at)
        torque.addStretch()
        layout.addLayout(torque)
        box, form = self._section("TCC View Settings")
        p = f"{base}.master.tcc_view"
        self.add_int(form, "Test Point", f"{p}.test_point_a", 1, 6000, " A")
        self.add_int(form, "Min. Current", f"{p}.min_current_a", 1, 19999, " A")
        self.add_int(form, "Max. Current", f"{p}.max_current_a", 2, 20000, " A")
        self.add_float(form, "Min. Time", f"{p}.min_time_s", 0.001, 9998, 3, " s")
        self.add_float(form, "Max. Time", f"{p}.max_time_s", 0.002, 9999, 3, " s")
        self.add_bool(form, "Log10 Current Axis", f"{p}.log_current_axis")
        self.add_bool(form, "Log10 Time Axis", f"{p}.log_time_axis")
        layout.addWidget(box)
        layout.addWidget(
            self._element_table(
                "Earth Fault Overcurrent (EF)", f"{base}.ef", self.ELEMENT_NAMES
            )
        )
        return _scroll_widget(content)

    def _reclose_section(self, title: str, path: str) -> QGroupBox:
        box, form = self._section(title)
        self.add_float(
            form, "1st Reclose Time (Tr1)", f"{path}.reclose_1_s", 0.1, 180, 2, " s"
        )
        self.add_float(
            form, "2nd Reclose Time (Tr2)", f"{path}.reclose_2_s", 1, 180, 2, " s"
        )
        self.add_float(
            form, "3rd Reclose Time (Tr3)", f"{path}.reclose_3_s", 1, 180, 2, " s"
        )
        self.add_float(form, "Reset Time (Tres)", f"{path}.reset_s", 5, 180, 2, " s")
        return box

    def _sef_tab(self, base: str) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(
            self._element_table(
                "Sensitive Earth Fault (SEF)", f"{base}.sef", ("SEF+", "SEF-")
            )
        )
        angle = QHBoxLayout()
        angle.addWidget(QLabel("SEF Torque Angle"))
        value = QSpinBox()
        value.setRange(0, 359)
        value.setSuffix(" °")
        self._bind(f"{base}.sef.torque_angle_deg", value)
        angle.addWidget(value)
        angle.addStretch()
        layout.addLayout(angle)
        row = QHBoxLayout()
        row.addWidget(
            self._reclose_section("OCEF Reclosing (AR OCEF)", f"{base}.ar_ocef")
        )
        layout.addLayout(row)
        layout.addStretch()
        box, form = self._section("OCEF Reclosing Controls")
        self.add_bool(form, "VRC", f"{base}.ar_ocef.vrc")
        self.add_combo(
            form, "LSRM Mode", f"{base}.ar_ocef.lsrm_mode", ("DISABLE", "ENABLE")
        )
        self.add_float(
            form, "LSRM Time", f"{base}.ar_ocef.lsrm_time_s", 1, 300, 2, " s"
        )
        layout.insertWidget(layout.count() - 1, box)
        return _scroll_widget(content)

    def _auxiliary_tab(self, base: str) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        box, form = self._section("Cold Load Pickup (CLP)")
        self.add_float(form, "Multiplier (CLM)", f"{base}.clp.multiplier", 1, 5, 1)
        self.add_int(form, "Time (Tcl)", f"{base}.clp.time_min", 1, 400, " min")
        self.add_int(
            form,
            "Recognition Time (Trec)",
            f"{base}.clp.recognition_min",
            1,
            60,
            " min",
        )
        grid.addWidget(box, 0, 0)
        box, form = self._section("Inrush Restraint (IR)")
        self.add_float(form, "Multiplier (IRM)", f"{base}.inrush.multiplier", 1, 20, 1)
        self.add_float(form, "Time (Tir)", f"{base}.inrush.time_s", 0.01, 10, 2, " s")
        grid.addWidget(box, 0, 1)
        box, form = self._section("Live Line")
        for element in ("oc", "ef"):
            prefix = element.upper()
            path = f"{base}.live_line.{element}"
            self.add_int(
                form, f"{prefix} Pickup Current", f"{path}.pickup_a", 20, 6000, " A"
            )
            self.add_float(
                form,
                f"{prefix} Tripping Time",
                f"{path}.tripping_time_s",
                0,
                120,
                2,
                " s",
            )
        grid.addWidget(box, 1, 0)
        grid.setRowStretch(2, 1)
        return _scroll_widget(content)

    def _voltage_tab(self, base: str) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        box, form = self._section("Under Voltage")
        for name in ("uv1", "uv12", "uv13", "uv2", "uv22", "uv23", "uv3"):
            path = f"{base}.voltage.{name}"
            title = name.upper()
            if name != "uv3":
                self.add_float(
                    form, f"{title} Multiplier", f"{path}.multiplier", 0.6, 1.0, 2
                )
            self.add_float(
                form, f"{title} Trip Time", f"{path}.trip_s", 0, 180, 2, " s"
            )
        grid.addWidget(box, 0, 0)
        box, form = self._section("Automatic Backfeed Restoration (ABR)")
        p = f"{base}.abr"
        self.add_bool(form, "Enabled", "protection.feature_flags.abr")
        self.add_float(form, "Restoration Time", f"{p}.reset_s", 0, 180, 2, " s")
        self.add_combo(
            form,
            "Auto Open Mode",
            f"{p}.auto_open_mode",
            ("DISABLE", "TIMER", "POWER FLOW"),
        )
        self.add_int(form, "Timer", f"{p}.timer.time_min", 1, 300, " min")
        self.add_int(form, "Operations", f"{p}.timer.operations", 0, 10)
        self.add_bool(form, "Direction Changed", f"{p}.power_flow.direction_changed")
        self.add_bool(form, "Reduced", f"{p}.power_flow.reduced")
        self.add_int(
            form, "Reduced Percent", f"{p}.power_flow.reduced_percent", 50, 90, " %"
        )
        self.add_float(
            form, "Power Flow Time", f"{p}.power_flow.time_s", 1, 300, 2, " s"
        )
        self.add_bool(form, "Recloser Enabled", f"{base}.recloser_enabled")
        grid.addWidget(box, 0, 1)
        grid.setRowStretch(2, 1)
        return _scroll_widget(content)

    def _directional_master(self, base: str) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        for index, name in enumerate(("oc", "ef", "nps", "sef")):
            box, form = self._section(f"{name.upper()} Directional")
            p = f"{base}.master.directional.{name}"
            torque_path = f"{base}.{name}.torque_angle_deg"
            self.add_int(form, "Torque Angle", torque_path, 0, 359, " °")
            self.add_combo(
                form,
                "Not Detected",
                f"{p}.not_detected",
                ("BLOCK", "TRIP"),
            )
            self.add_combo(
                form,
                "Change Response",
                f"{p}.change_response",
                ("LOCK", "DYNAMIC"),
            )
            labels = (
                ("1+", "2+", "3+", "1-", "2-", "3-")
                if name != "sef"
                else ("SEF+", "SEF-")
            )
            for stage, label in enumerate(labels):
                self.add_bool(form, f"Enable {label}", f"{p}.stages.{stage}")
            grid.addWidget(box, index // 2, index % 2)
        box, form = self._section("Admittance (Yn)")
        p = f"{base}.master.admittance"
        for stage in range(4):
            self.add_combo(
                form, f"AR Mode {stage + 1}", f"{p}.ar_modes.{stage}", AR_MODES
            )
        self.add_combo(
            form,
            "Operational Mode",
            f"{p}.operational_mode",
            ("GN", "BN", "GN&BN"),
        )
        self.add_combo(
            form,
            "Directional Mode",
            f"{p}.directional_mode",
            ("FORWARD", "REVERSE", "ANY"),
        )
        for label, name, low, high in (
            ("Min. Un Mult.", "min_un_multiplier", 0.01, 1),
            ("Tripping Time", "trip_s", 0, 120),
            ("Reset Time", "reset_s", 0, 10),
            ("Minimum In", "minimum_in_a", 3, 1280),
            ("Forward Susceptance", "forward_susceptance", -327, 327),
            ("Reverse Susceptance", "reverse_susceptance", -327, 327),
            ("Forward Conductance", "forward_conductance", -327, 327),
            ("Reverse Conductance", "reverse_conductance", -327, 327),
        ):
            self.add_float(form, label, f"{p}.{name}", low, high, 2)
        grid.addWidget(box, 2, 0, 1, 2)
        return _scroll_widget(content)

    def _quality_master(self, base: str) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        box, form = self._section("Inrush Restraint / Harmonic Blocking")
        p = f"{base}.inrush"
        self.add_float(form, "Multiplier", f"{p}.multiplier", 1, 20, 1)
        self.add_float(form, "Time", f"{p}.time_s", 0, 10, 2, " s")
        for order, prefix in (("2nd", "second"), ("5th", "fifth")):
            self.add_bool(
                form, f"{order} Harmonic Blocking", f"{p}.{prefix}_harmonic_enabled"
            )
            self.add_float(
                form,
                f"{order} Harmonic Level",
                f"{p}.{prefix}_harmonic_level_pct",
                0,
                100,
                1,
                " %",
            )
            self.add_float(
                form,
                f"{order} Harmonic Time",
                f"{p}.{prefix}_harmonic_time_s",
                0.05,
                120,
                2,
                " s",
            )
        self.add_bool(form, "SST Control", f"{p}.sst_control_enabled")
        self.add_float(
            form, "SST Control Time", f"{p}.sst_control_time_s", 0, 180, 2, " s"
        )
        grid.addWidget(box, 0, 0)
        box, form = self._section("Overload")
        p = f"{base}.master.overload"
        self.add_int(
            form, "Zero Sequence Current Min.", f"{p}.zero_sequence_min_a", 0, 100, " A"
        )
        self.add_int(
            form,
            "Negative Sequence Current Min.",
            f"{p}.negative_sequence_min_a",
            0,
            100,
            " A",
        )
        for section in ("symmetrical", "asymmetrical"):
            self.add_combo(
                form,
                f"{section.title()} Mode",
                f"{p}.{section}.mode",
                ("DISABLE", "ALARM", "TRIP"),
            )
            self.add_int(
                form,
                f"{section.title()} Pickup",
                f"{p}.{section}.pickup_a",
                10,
                1280,
                " A",
            )
            self.add_float(
                form,
                f"{section.title()} Trip Time",
                f"{p}.{section}.trip_s",
                60,
                9999,
                2,
                " s",
            )
            self.add_float(
                form,
                f"{section.title()} Reset",
                f"{p}.{section}.reset_s",
                0,
                120,
                2,
                " s",
            )
        grid.addWidget(box, 0, 1)
        box, form = self._section("Broken Conductor (46BC)")
        p = f"{base}.master.broken_conductor"
        self.add_combo(form, "Mode", f"{p}.mode", ("DISABLE", "ALARM", "TRIP"))
        self.add_int(form, "Pickup Value", f"{p}.pickup_pct", 10, 100, " %")
        self.add_int(
            form,
            "Negative Sequence Min.",
            f"{p}.negative_sequence_min_a",
            3,
            1280,
            " A",
        )
        self.add_float(form, "Tripping Time", f"{p}.trip_s", 0, 120, 2, " s")
        grid.addWidget(box, 1, 0, 1, 2)
        return _scroll_widget(content)

    def _voltage_master(self, base: str) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        over_voltage_titles = {
            "ov1": "Phase Over Voltage (OV1)",
            "ov12": "Phase Over Voltage (OV12)",
            "ov13": "Phase Over Voltage (OV13)",
            "ov2": "Line-to-Line Over Voltage (OV2)",
            "ov22": "Line-to-Line Over Voltage (OV22)",
            "ov23": "Line-to-Line Over Voltage (OV23)",
            "ov3": "Neutral Displacement (OV3)",
            "ov4": "Negative Sequence Over Voltage (OV4)",
        }
        for index, key in enumerate(over_voltage_titles):
            box, form = self._section(over_voltage_titles[key])
            p = f"{base}.master.over_voltage.{key}"
            multiplier_range = (
                (1.0, 1.5)
                if key in {"ov1", "ov12", "ov13", "ov2", "ov22", "ov23"}
                else (0.01, 1.0)
            )
            self.add_float(
                form,
                "Voltage Multiplier",
                f"{p}.multiplier",
                multiplier_range[0],
                multiplier_range[1],
                2,
            )
            self.add_float(form, "Tripping Time", f"{p}.trip_s", 0, 180, 2, " s")
            self.add_combo(form, "AR Mode", f"{p}.ar_mode", AR_MODES)
            if key == "ov3":
                self.add_combo(
                    form,
                    "Moving Average Mode",
                    f"{p}.moving_average_mode",
                    ("DISABLE", "ENABLE"),
                )
                self.add_float(
                    form,
                    "Moving Average Window",
                    f"{p}.moving_average_window",
                    0.1,
                    10,
                    1,
                    " s",
                )
            grid.addWidget(box, index // 2, index % 2)
        box, form = self._section("Auto Reclosing Voltage Element")
        p = f"{base}.master.ar_voltage"
        self.add_float(form, "Reclose Time", f"{p}.reclose_s", 0, 180, 2, " s")
        self.add_int(form, "No. of Trips to Lockout", f"{p}.trip_count", 1, 4)
        for key in (
            "ov1", "ov12", "ov13", "ov2", "ov22", "ov23", "ov3", "ov4",
            "uv1", "uv12", "uv13", "uv2", "uv22", "uv23", "uv3",
        ):
            self.add_combo(form, key.upper(), f"{p}.{key}", AR_MODES)
        self.add_bool(form, "Operation in SST Only", f"{p}.sst_only")
        self.add_bool(form, "AutoClose Mode", f"{p}.auto_close")
        self.add_float(form, "AutoClose Time", f"{p}.auto_close_s", 0, 180, 2, " s")
        grid.addWidget(box, 4, 0, 1, 2)
        return _scroll_widget(content)

    def _harmonic_master(self, base: str) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        p = f"{base}.master.frequency"
        for index, key in enumerate(("under", "over")):
            box, form = self._section(f"{key.title()} Frequency")
            self.add_combo(
                form, "Mode", f"{p}.{key}.mode", ("DISABLE", "ALARM", "TRIP")
            )
            self.add_float(
                form,
                "Pickup Frequency",
                f"{p}.{key}.pickup_hz",
                45 if key == "under" else 50,
                50 if key == "under" else 55,
                2,
                " Hz",
            )
            self.add_float(
                form, "Tripping Time", f"{p}.{key}.trip_s", 0.05, 120, 2, " s"
            )
            grid.addWidget(box, 0, index)
        box, form = self._section("VRC / Live Load Blocking")
        self.add_combo(form, "VRC Mode", f"{p}.vrc.mode", ("ABC", "RST", "RING"))
        self.add_float(
            form, "VRC Voltage Multiplier", f"{p}.vrc.voltage_multiplier", 0.6, 0.95, 2
        )
        self.add_bool(form, "LLB Mode", f"{p}.llb.mode")
        self.add_float(
            form, "LLB Voltage Multiplier", f"{p}.llb.voltage_multiplier", 0.6, 0.95, 2
        )
        grid.addWidget(box, 1, 0)
        box, form = self._section("THD / TDD")
        p = f"{base}.master.harmonic"
        for key, title in (("thd", "Voltage THD"), ("tdd", "Current TDD")):
            self.add_combo(
                form, f"{title} Mode", f"{p}.{key}.mode", ("DISABLE", "ALARM", "TRIP")
            )
            self.add_float(
                form, f"{title} Level", f"{p}.{key}.level_pct", 1, 100, 1, " %"
            )
            self.add_float(
                form, f"{title} Tripping Time", f"{p}.{key}.trip_s", 1, 120, 2, " s"
            )
        grid.addWidget(box, 1, 1)
        box, form = self._section("Individual Harmonics (IND HRM)")
        self.add_combo(
            form, "Mode", f"{p}.individual.mode", ("DISABLE", "ALARM", "TRIP")
        )
        self.add_float(form, "Tripping Time", f"{p}.individual.trip_s", 1, 120, 2, " s")
        individual_harmonics = (
            "DISABLE",
            *(f"I{order}" for order in range(2, 16)),
            *(f"IN{order}" for order in range(2, 16)),
            *(f"V{order}" for order in range(2, 16)),
        )
        for index, label in enumerate("ABCDE"):
            item = f"{p}.individual.items.{index}"
            self.add_combo(
                form,
                f"Harmonic {label}",
                f"{item}.mode",
                individual_harmonics,
            )
            self.add_float(
                form, f"Harmonic {label} Level", f"{item}.level_pct", 1, 100, 1, " %"
            )
        grid.addWidget(box, 2, 0, 1, 2)
        return _scroll_widget(content)

    def _sectionalizer_master(self, base: str) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        box, form = self._section("Sectionalizing")
        p = f"{base}.sectionalizing"
        self.add_combo(form, "State", f"{p}.state", ("ALARM", "TRIP/LOCK"))
        self.add_int(form, "Max Trip Count", f"{p}.max_trip_count", 1, 3)
        self.add_float(form, "Reset Time", f"{p}.reset_time_s", 0, 1200, 2, " s")
        grid.addWidget(box, 0, 0)
        grid.setRowStretch(1, 1)
        return _scroll_widget(content)

    def _sectionalizer_protection_tab(self, base: str) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        for index, (key, title) in enumerate(
            (
                ("oc", "Phase Overcurrent (OC)"),
                ("ef", "Earth Fault Overcurrent (EF)"),
                ("sef", "Sensitive Earth Fault (SEF)"),
            )
        ):
            box, form = self._section(title)
            path = f"{base}.{key}.elements.1"
            pickup_range = (1, 80) if key == "sef" else (20, 6000)
            trip_max = 120 if key == "sef" else 2
            self.add_int(
                form,
                "Pickup Current",
                f"{path}.pickup_a",
                pickup_range[0],
                pickup_range[1],
                " A",
            )
            self.add_float(
                form, "Tripping Time", f"{path}.tripping_time_s", 0, trip_max, 2, " s"
            )
            self.add_float(
                form, "Reset Time", f"{path}.reset_time_s", 0, 10, 2, " s"
            )
            grid.addWidget(box, index // 2, index % 2)
        note = QLabel(
            "Sectionalizer protection uses one forward OC, EF and SEF element, "
            "matching the original company menu."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        grid.addWidget(note, 2, 0, 1, 2)
        grid.setRowStretch(3, 1)
        return _scroll_widget(content)

    def _sectionalizer_voltage_tab(self, base: str) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        for column, (key, title) in enumerate(
            (("uv1", "Phase Under Voltage (UV1)"), ("uv3", "Loss of Supply (UV3)"))
        ):
            box, form = self._section(title)
            path = f"{base}.voltage.{key}"
            mode = QComboBox()
            mode.setProperty("bindItemData", True)
            for text, value in (
                ("DISABLE", "DISABLE"),
                ("ALARM", "ALARM"),
                ("TRIP", "RECLOSE"),
            ):
                mode.addItem(text, value)
            self._bind(f"{base}.master.ar_voltage.{key}", mode)
            form.addRow("Mode", mode)
            if key == "uv1":
                self.add_float(
                    form,
                    "Voltage Multiplier",
                    f"{path}.multiplier",
                    0.6,
                    1.0,
                    2,
                )
            self.add_float(form, "Tripping Time", f"{path}.trip_s", 0, 180, 2, " s")
            grid.addWidget(box, 0, column)

        box, form = self._section("Broken Conductor (46BC)")
        path = f"{base}.master.broken_conductor"
        self.add_combo(form, "Mode", f"{path}.mode", ("DISABLE", "ALARM", "TRIP"))
        self.add_int(form, "Pickup Value", f"{path}.pickup_pct", 10, 100, " %")
        self.add_int(
            form,
            "Negative Sequence Min.",
            f"{path}.negative_sequence_min_a",
            3,
            1280,
            " A",
        )
        self.add_float(form, "Tripping Time", f"{path}.trip_s", 0, 120, 2, " s")
        grid.addWidget(box, 1, 0)

        box, form = self._section("Live Load Blocking (LLB)")
        path = f"{base}.master.frequency.llb"
        self.add_bool(form, "Enabled", f"{path}.mode")
        self.add_combo(
            form,
            "Load Side",
            f"{base}.master.frequency.vrc.mode",
            ("ABC", "RST", "RING"),
        )
        self.add_float(
            form, "Voltage Multiplier", f"{path}.voltage_multiplier", 0.6, 0.95, 2
        )
        grid.addWidget(box, 1, 1)
        grid.setRowStretch(2, 1)
        return _scroll_widget(content)

    def _open_tcc_dialog(
        self,
        title: str,
        path: str,
        names: tuple[str, ...],
        selected_index: int,
    ) -> TccChartDialog | None:
        if self._config is None:
            return None
        self.update_config(self._config)
        family = _get_path(self._config, path)
        group_path = path.rsplit(".", 1)[0]
        view_settings = _get_path(self._config, f"{group_path}.master.tcc_view")
        dialog = TccChartDialog(
            title,
            names,
            family["elements"],
            selected_index,
            view_settings,
            self,
        )
        native = getattr(self, "native_settings", None)
        if native is not None and not title.startswith("SEF"):
            group_index = int(group_path.split(".")[2])
            family_key = {"oc": "o", "ef": "e", "nps": "nps"}.get(path.rsplit(".", 1)[1])
            pack = native["p"]["g"][group_index].get(family_key, {})
            available = all("mm" in pack.get(side, {}).get("f", {}).get("t", {}) for side in ("f", "r"))
            dialog.max_mode.setEnabled(available)
            if not available:
                dialog.max_mode.setToolTip("Not exposed by the company BeachEye JSON API.")
        self._chart_dialogs.add(dialog)
        dialog.finished.connect(
            lambda _result: self._finish_tcc_dialog(dialog)
        )
        dialog.show()
        return dialog

    def _finish_tcc_dialog(self, dialog: TccChartDialog) -> None:
        self._chart_dialogs.discard(dialog)
        if self._config is not None:
            self.apply_config(self._config)

    def set_device_model(self, model: str) -> None:
        normalized = model.strip().upper()
        is_sectionalizer = normalized.endswith("S") or normalized == "SECTIONALIZER"
        self._device_model = "FC22S" if is_sectionalizer else "FC22AR"
        self.device_badge.setText(
            "SECTIONALIZER · FC22S" if is_sectionalizer else "AUTO RECLOSER · FC22AR"
        )

        sectionalizer_globals = {
            "enabled",
            "oc_enabled",
            "ef_enabled",
            "sef_enabled",
            "voltage_enabled",
            "live_line_enabled",
        }
        for name, widget in self._global_widgets.items():
            widget.setVisible(not is_sectionalizer or name in sectionalizer_globals)
        self._global_widgets["live_line_enabled"].setText(
            "Enable Synchronism" if is_sectionalizer else "Live Line"
        )

        sectionalizer_features = {"llb", "sectionalizer", "breaker"}
        for name, widget in self._feature_widgets.items():
            widget.setVisible(
                name in sectionalizer_features
                if is_sectionalizer
                else name not in {"sectionalizer", "breaker"}
            )

        for tabs in self._group_tabs:
            for index in range(tabs.count()):
                tabs.setTabVisible(
                    index,
                    index >= 6 if is_sectionalizer else index < 6,
                )
            tabs.setCurrentIndex(6 if is_sectionalizer else 0)

        for tabs in self._master_extension_tabs:
            if tabs.count() > 4:
                tabs.setTabVisible(4, is_sectionalizer)
            for index in range(min(4, tabs.count())):
                tabs.setTabVisible(index, not is_sectionalizer)

    def apply_config(self, config: dict[str, Any]) -> None:
        self._config = config
        super().apply_config(config)
        for curve, refresh in self._tcc_field_refreshers:
            refresh(curve.currentText())
        index = max(0, min(3, int(config["protection"]["active_group"]) - 1))
        self.group_select.setCurrentIndex(index)
        self.group_stack.setCurrentIndex(index)

    def update_config(self, config: dict[str, Any]) -> None:
        super().update_config(config)
        config["protection"]["active_group"] = self.group_select.currentIndex() + 1
