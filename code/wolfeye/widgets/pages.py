from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

from wolfeye.branding import PRODUCT_NAME
from wolfeye.qt import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QRectF,
    Qt,
    Signal,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    event_position,
)

from wolfeye.models import DeviceInfo, EventRecord, MeasurementSnapshot
from wolfeye.point_schema import (
    ANALOG_POINT_NAMES,
    BINARY_INPUT_POINT_NAMES,
    BINARY_OUTPUT_COMMANDS,
    BINARY_OUTPUT_POINT_NAMES,
)
from wolfeye.services.beacheye import SIGNAL_CHANNEL_NAMES, SIGNAL_SAMPLES
from wolfeye.services.signal_analysis import (
    MovingSignalAnalysis,
    SignalAnalysisError,
    SignalAnalysisResult,
    SignalAnalyzer,
)
from wolfeye.widgets.signal_analysis import (
    SignalAnalysisSummaryWidget,
    SignalAnalysisWindow,
)


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—", suffix: str = "") -> None:
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        self.value_label = QLabel(value + suffix)
        self.value_label.setObjectName("metricValue")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class StatusPage(QWidget):
    control_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._device_model = "FC22AR"
        root = QVBoxLayout(self)
        cards = QGridLayout()
        self.model = MetricCard("DEVICE", "—")
        self.firmware = MetricCard("FIRMWARE", "—")
        self.voltage = MetricCard("BATTERY", "—")
        self.temperature = MetricCard("TEMPERATURE", "—")
        for index, card in enumerate(
            (self.model, self.firmware, self.voltage, self.temperature)
        ):
            cards.addWidget(card, 0, index)
        root.addLayout(cards)

        electrical = QGridLayout()
        self.current_cards = {
            name: MetricCard(name, "—") for name in ("Ia", "Ib", "Ic", "In")
        }
        self.voltage_cards = {
            name: MetricCard(name, "—") for name in ("Uab", "Ubc", "Uca")
        }
        for column, card in enumerate(self.current_cards.values()):
            electrical.addWidget(card, 0, column)
        for column, card in enumerate(self.voltage_cards.values()):
            electrical.addWidget(card, 1, column)
        root.addLayout(electrical)

        state_box = QGroupBox("Switchgear state")
        state_layout = QHBoxLayout(state_box)
        self.breaker = QLabel("UNKNOWN")
        self.breaker.setObjectName("metricValue")
        state_layout.addWidget(self.breaker)
        state_layout.addStretch()

        open_btn = QPushButton("OPEN")
        open_btn.setObjectName("success")
        close_btn = QPushButton("CLOSE")
        close_btn.setObjectName("danger")

        refresh_btn = QPushButton("Read status")
        open_btn.clicked.connect(lambda: self.control_requested.emit("OPEN"))
        close_btn.clicked.connect(lambda: self.control_requested.emit("CLOSE"))
        refresh_btn.clicked.connect(self.refresh_requested)
        state_layout.addWidget(open_btn)
        state_layout.addWidget(close_btn)
        state_layout.addWidget(refresh_btn)
        root.addWidget(state_box)

        summary = QGroupBox("System summary")
        self.summary_grid = QGridLayout(summary)
        self.summary_title_labels: dict[str, QLabel] = {}
        self.summary_labels: dict[str, QLabel] = {}
        names = [
            "Remote",
            "Protection",
            "OC",
            "EF",
            "SEF",
            "AR",
            "AC supply",
            "Mechanical Lock",
            "Gas Low",
            "Synch. Failure",
            "Reverse Power",
            "Charging",
            "Ua",
            "Ub",
            "Uc",
            "Ur",
            "Us",
            "Ut",
        ]
        for i, name in enumerate(names):
            title = QLabel(name)
            label = QLabel("● OFF")
            self.summary_title_labels[name] = title
            self.summary_labels[name] = label
            self.summary_grid.addWidget(title, i // 4 * 2, i % 4)
            self.summary_grid.addWidget(label, i // 4 * 2 + 1, i % 4)
        root.addWidget(summary)
        root.addStretch()

    def set_device_model(self, model: str) -> None:
        normalized = model.strip().upper()
        self._device_model = (
            "FC22S"
            if normalized.endswith("S") or normalized == "SECTIONALIZER"
            else "FC22AR"
        )
        is_sectionalizer = self._device_model == "FC22S"
        self.summary_title_labels["AR"].setText(
            "Sectionalizing" if is_sectionalizer else "AR"
        )

    def set_device(self, info: DeviceInfo) -> None:
        self.model.set_value(info.model)
        self.firmware.set_value(f"FW {info.firmware} / HW {info.hardware}")

    def set_measurements(self, data: MeasurementSnapshot) -> None:
        def measured(name: str, scale: float, unit: str) -> str:
            value = data.analog.get(name)
            return "—" if value is None else f"{value / scale:.1f} {unit}"

        self.voltage.set_value(measured("Battery Voltage", 10, "V"))
        self.temperature.set_value(measured("Temperature", 10, "°C"))
        for name, card in self.current_cards.items():
            card.set_value(measured(name, 10, "A"))
        for name, card in self.voltage_cards.items():
            card.set_value(measured(name, 1000, "kV"))
        opened = data.binary.get("Open", False)
        closed = data.binary.get("Closed", False)
        self.breaker.setText(
            "OPEN"
            if opened and not closed
            else "CLOSED"
            if closed and not opened
            else "UNKNOWN"
        )
        mapping = {
            "Remote": ("Remote Control", "Remote On"),
            "Protection": ("Prot On",),
            "OC": ("OC On",),
            "EF": ("EF On",),
            "SEF": ("SEF On",),
            "AR": (
                ("CLP On", "Sectionalizing")
                if self._device_model == "FC22S"
                else ("AR On",)
            ),
            "AC supply": ("AC supply",),
            "Mechanical Lock": ("Mechanically Locked", "Mechanical Lock"),
            "Gas Low": ("Low Gas Pressure",),
            # These two indicators use the same bit in the company Status view.
            "Synch. Failure": ("Timed Sync-check", "Synch. Fail"),
            "Reverse Power": ("Timed Sync-check", "Synch. Fail"),
            "Charging": ("Charging",),
            "Ua": ("P(Ua)", "Ua"),
            "Ub": ("P(Ub)", "Ub"),
            "Uc": ("P(Uc)", "Uc"),
            "Ur": ("P(Ur)", "Ur"),
            "Us": ("P(Us)", "Us"),
            "Ut": ("P(Ut)", "Ut"),
        }
        for title, keys in mapping.items():
            enabled = next(
                (data.binary[key] for key in keys if key in data.binary), None
            )
            label = self.summary_labels[title]
            label.setText("● UNKNOWN" if enabled is None else "● ON" if enabled else "● OFF")
            label.setStyleSheet(f"color: {'#56d694' if enabled else '#68788e'}")


class MeasurementPage(QWidget):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        tools = QHBoxLayout()
        self.updated = QLabel("No data")
        self.updated.setObjectName("muted")
        self.refresh_button = QPushButton("Refresh now")
        self.refresh_button.setEnabled(False)
        self.refresh_button.clicked.connect(self.refresh_requested)
        tools.addWidget(QLabel("Live measurements"))
        tools.addStretch()
        tools.addWidget(self.updated)
        tools.addWidget(self.refresh_button)
        root.addLayout(tools)
        columns = QHBoxLayout()
        self.binary = self._point_group("Binary Inputs", ("ID", "Description", "Value"))
        self.analog = self._point_group("Analog Inputs", ("ID", "Description", "Value"))
        self.outputs = self._point_group(
            "Binary Outputs", ("ID", "Description", "Required Command")
        )
        for box in (self.binary, self.analog, self.outputs):
            columns.addWidget(box, 1)
        root.addLayout(columns, 1)
        self.binary_table = self.binary.findChild(QTableWidget)
        self.analog_table = self.analog.findChild(QTableWidget)
        self.output_table = self.outputs.findChild(QTableWidget)
        self._prime(
            self.binary_table, [(name, "False") for name in BINARY_INPUT_POINT_NAMES]
        )
        self._prime(self.analog_table, [(name, "0") for name in ANALOG_POINT_NAMES])
        self._prime(
            self.output_table,
            list(zip(BINARY_OUTPUT_POINT_NAMES, BINARY_OUTPUT_COMMANDS)),
        )

    def set_connected(self, connected: bool) -> None:
        self.refresh_button.setEnabled(connected)

    @staticmethod
    def _point_group(title: str, headers: tuple[str, str, str]) -> QGroupBox:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(headers)
        table.setColumnWidth(0, 42)
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        layout.addWidget(table)
        return box

    @staticmethod
    def _prime(table: QTableWidget, values: list[tuple[str, str]]) -> None:
        table.setRowCount(len(values))
        for row, (name, value) in enumerate(values):
            table.setItem(row, 0, QTableWidgetItem(str(row)))
            table.setItem(row, 1, QTableWidgetItem(name))
            table.setItem(row, 2, QTableWidgetItem(value))

    @staticmethod
    def _fill(table: QTableWidget, values: dict[str, Any], bools: bool = False,
              indices: dict[str, int] | None = None) -> None:
        table.setRowCount(len(values))
        items = sorted(values.items(), key=lambda item: indices[item[0]]) if indices else values.items()
        for row, (name, value) in enumerate(items):
            table.setItem(row, 0, QTableWidgetItem(str(indices[name] if indices else row)))
            table.setItem(row, 1, QTableWidgetItem(name))
            text = (
                "True"
                if value and bools
                else "False"
                if bools
                else f"{value:,.2f}"
                if isinstance(value, float)
                else str(value)
            )
            item = QTableWidgetItem(text)
            if bools:
                item.setBackground(QColor("#8fe3a4" if value else "#f29a9a"))
            table.setItem(row, 2, item)

    def update_snapshot(self, data: MeasurementSnapshot) -> None:
        self._fill(self.analog_table, data.analog, indices=data.analog_indices)
        self._fill(self.binary_table, data.binary, True, data.binary_indices)
        self.updated.setText(data.timestamp.strftime("Updated %H:%M:%S"))


class Waveform(QWidget):
    """Interactive, dependency-free waveform with linked horizontal navigation."""

    COLORS = ("#0067b8", "#087f23", "#d14f00", "#7b2cbf", "#00838f", "#c2185b")
    view_changed = Signal(float, float)

    def __init__(self, channel_names: tuple[str, ...]) -> None:
        super().__init__()
        self.channel_names = channel_names
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.samples: list[list[float]] = []
        self.channel_visible = [True] * len(channel_names)
        self.sample_rate_hz: float | None = None
        self.time_origin_samples = 0
        self.fault_boundary: str | None = None
        self.view_start = 0.0
        self.view_end = 1.0
        self._cursor_x: float | None = None
        self._drag: tuple[float, float, float] | None = None

    def set_samples(
        self,
        samples: list[list[float]],
        sample_rate_hz: float | None = None,
        time_origin_samples: int = 0,
        fault_boundary: str | None = None,
    ) -> None:
        self.samples = samples
        self.sample_rate_hz = sample_rate_hz
        self.time_origin_samples = time_origin_samples
        self.fault_boundary = fault_boundary
        self.reset_zoom()

    def set_channel_visible(self, index: int, visible: bool) -> None:
        if 0 <= index < len(self.channel_visible):
            self.channel_visible[index] = visible
            self.update()

    def set_view_range(self, start: float, end: float, emit: bool = False) -> None:
        count = self._sample_count()
        if count < 2:
            return
        span = min(max(end - start, 3.0), count - 1.0)
        start = min(max(start, 0.0), count - 1.0 - span)
        end = start + span
        changed = abs(start - self.view_start) > 1e-6 or abs(end - self.view_end) > 1e-6
        self.view_start, self.view_end = start, end
        if changed:
            self.update()
            if emit:
                self.view_changed.emit(start, end)

    def reset_zoom(self) -> None:
        count = self._sample_count()
        self.view_start = 0.0
        self.view_end = float(max(1, count - 1))
        self._cursor_x = None
        self.update()
        if count > 1:
            self.view_changed.emit(self.view_start, self.view_end)

    def zoom(self, factor: float, center: float | None = None) -> None:
        count = self._sample_count()
        if count < 2:
            return
        center = (self.view_start + self.view_end) / 2 if center is None else center
        new_span = (self.view_end - self.view_start) * factor
        ratio = (center - self.view_start) / max(self.view_end - self.view_start, 1e-9)
        self.set_view_range(center - ratio * new_span, center + (1 - ratio) * new_span, True)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        plot = QRectF(52, 16, max(1, self.width() - 66), max(1, self.height() - 48))
        painter.fillRect(plot, QColor("#fbfcfe"))
        self._draw_grid(painter, plot)

        populated = [
            values
            for index, values in enumerate(self.samples)
            if values and index < len(self.channel_visible) and self.channel_visible[index]
        ]
        if not populated:
            painter.setPen(QColor("#666666"))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "No signal loaded")
            return

        first = max(0, int(math.floor(self.view_start)))
        last = min(max(len(values) for values in populated) - 1, int(math.ceil(self.view_end)))
        visible_values = [value for values in populated for value in values[first : last + 1]]
        minimum, maximum = min(visible_values), max(visible_values)
        padding = (maximum - minimum) * 0.06 or max(abs(maximum), 1.0) * 0.06
        minimum -= padding
        maximum += padding
        span = maximum - minimum
        self._draw_y_labels(painter, plot, minimum, maximum)

        painter.save()
        painter.setClipRect(plot)
        for channel_index, (values, color) in enumerate(zip(self.samples, self.COLORS)):
            if channel_index >= len(self.channel_visible) or not self.channel_visible[channel_index]:
                continue
            start = max(0, int(math.floor(self.view_start)))
            stop = min(len(values) - 1, int(math.ceil(self.view_end)))
            if stop <= start:
                continue
            path = QPainterPath()
            for index in range(start, stop + 1):
                x = self._sample_to_x(index, plot)
                y = plot.bottom() - (values[index] - minimum) * plot.height() / span
                path.moveTo(x, y) if index == start else path.lineTo(x, y)
            painter.setPen(QPen(QColor(color), 1.8))
            painter.drawPath(path)

        marker_x = plot.left() if self.fault_boundary == "start" else plot.right()
        if self.fault_boundary in {"start", "end"}:
            painter.setPen(QPen(QColor("#c62828"), 2, Qt.PenStyle.DashLine))
            painter.drawLine(int(marker_x), int(plot.top()), int(marker_x), int(plot.bottom()))
        if self._cursor_x is not None and plot.contains(self._cursor_x, plot.center().y()):
            painter.setPen(QPen(QColor("#455a64"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(self._cursor_x), int(plot.top()), int(self._cursor_x), int(plot.bottom()))
        painter.restore()

        if self.fault_boundary in {"start", "end"}:
            painter.setPen(QColor("#c62828"))
            align = Qt.AlignmentFlag.AlignLeft if self.fault_boundary == "start" else Qt.AlignmentFlag.AlignRight
            painter.drawText(plot.adjusted(4, 2, -4, -2), align | Qt.AlignmentFlag.AlignTop, "FAULT")
        self._draw_cursor_readout(painter, plot)

    def _draw_grid(self, painter: QPainter, plot: QRectF) -> None:
        painter.setPen(QPen(QColor("#dde3ea"), 1))
        for step in range(9):
            x = plot.left() + plot.width() * step / 8
            painter.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))
            sample = self.view_start + (self.view_end - self.view_start) * step / 8
            label = self._time_label(sample)
            painter.setPen(QColor("#607080"))
            painter.drawText(QRectF(x - 35, plot.bottom() + 5, 70, 20), Qt.AlignmentFlag.AlignHCenter, label)
            painter.setPen(QPen(QColor("#dde3ea"), 1))
        for step in range(7):
            y = plot.top() + plot.height() * step / 6
            painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

    def _draw_y_labels(self, painter: QPainter, plot: QRectF, minimum: float, maximum: float) -> None:
        painter.setPen(QColor("#607080"))
        for step in range(4):
            y = plot.top() + plot.height() * step / 3
            value = maximum - (maximum - minimum) * step / 3
            painter.drawText(QRectF(0, y - 9, 47, 18), Qt.AlignmentFlag.AlignRight, f"{value:.3g}")

    def _draw_cursor_readout(self, painter: QPainter, plot: QRectF) -> None:
        if self._cursor_x is None or not plot.contains(self._cursor_x, plot.center().y()):
            return
        sample = int(round(self._x_to_sample(self._cursor_x, plot)))
        entries = []
        for index, (name, values) in enumerate(zip(self.channel_names, self.samples)):
            if index < len(self.channel_visible) and self.channel_visible[index] and sample < len(values):
                entries.append(f"{name} {values[sample]:.4g}")
        text = f"{self._time_label(sample)}  " + "  ".join(entries)
        width = min(plot.width() - 8, max(180, len(text) * 6.4))
        left = min(max(self._cursor_x + 8, plot.left() + 4), plot.right() - width - 4)
        box = QRectF(left, plot.top() + 5, width, 24)
        painter.fillRect(box, QColor(255, 255, 255, 235))
        painter.setPen(QColor("#263238"))
        painter.drawText(box.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter, text)

    def _time_label(self, sample: float) -> str:
        if self.sample_rate_hz and self.sample_rate_hz > 0:
            milliseconds = (self.time_origin_samples + sample) * 1000 / self.sample_rate_hz
            return f"{milliseconds:+.2f} ms" if self.fault_boundary else f"{milliseconds:.2f} ms"
        return f"S{int(round(sample))}"

    def _sample_count(self) -> int:
        return max((len(values) for values in self.samples), default=0)

    def _sample_to_x(self, sample: float, plot: QRectF) -> float:
        return plot.left() + (sample - self.view_start) * plot.width() / max(self.view_end - self.view_start, 1e-9)

    def _x_to_sample(self, x: float, plot: QRectF) -> float:
        return self.view_start + (x - plot.left()) * (self.view_end - self.view_start) / max(plot.width(), 1.0)

    def wheelEvent(self, event) -> None:
        plot = QRectF(52, 16, max(1, self.width() - 66), max(1, self.height() - 48))
        center = self._x_to_sample(event_position(event).x(), plot)
        self.zoom(0.75 if event.angleDelta().y() > 0 else 1.35, center)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = (event_position(event).x(), self.view_start, self.view_end)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            anchor_x, start, end = self._drag
            plot_width = max(1.0, self.width() - 66.0)
            shift = (anchor_x - event_position(event).x()) * (end - start) / plot_width
            self.set_view_range(start + shift, end + shift, True)
        else:
            self._cursor_x = event_position(event).x()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = None
            self.unsetCursor()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_zoom()

    def leaveEvent(self, event) -> None:
        del event
        self._cursor_x = None
        self.update()


class SignalPlotPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        navigation = QHBoxLayout()
        hint = QLabel("Wheel: zoom  ·  Drag: pan  ·  Double-click: reset  ·  Hover: inspect")
        hint.setObjectName("muted")
        navigation.addWidget(hint)
        navigation.addStretch()
        zoom_buttons: list[tuple[QToolButton, float]] = []
        for title, factor in (("−", 1.35), ("+", 0.75)):
            button = QToolButton()
            button.setText(title)
            button.setToolTip("Zoom out" if factor > 1 else "Zoom in")
            zoom_buttons.append((button, factor))
            navigation.addWidget(button)
        reset = QToolButton()
        reset.setText("Reset zoom")
        navigation.addWidget(reset)
        root.addLayout(navigation)

        plots = QVBoxLayout()
        plots.setSpacing(6)
        self.current_wave = self._signal_group(plots, "Currents", ("Ia", "Ib", "Ic", "In"))
        self.voltage_wave = self._signal_group(plots, "Voltages", ("Va", "Vb", "Vc", "Vr", "Vs", "Vt"))
        self.current_wave.view_changed.connect(
            lambda start, end: self.voltage_wave.set_view_range(start, end)
        )
        self.voltage_wave.view_changed.connect(
            lambda start, end: self.current_wave.set_view_range(start, end)
        )
        for button, factor in zoom_buttons:
            button.clicked.connect(
                lambda checked=False, value=factor: self.current_wave.zoom(value)
            )
        reset.clicked.connect(self.reset_zoom)
        root.addLayout(plots, 1)

    def reset_zoom(self) -> None:
        self.current_wave.reset_zoom()

    def set_cycle(
        self,
        channels: list[list[float]],
        sample_rate_hz: float | None,
        time_origin_samples: int,
        fault_boundary: str | None,
    ) -> None:
        self.current_wave.set_samples(channels[0:4], sample_rate_hz, time_origin_samples, fault_boundary)
        self.voltage_wave.set_samples(channels[4:10], sample_rate_hz, time_origin_samples, fault_boundary)

    @staticmethod
    def _signal_group(root: QVBoxLayout, title: str, names: tuple[str, ...]) -> Waveform:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        wave = Waveform(names)
        layout.addWidget(wave, 1)
        legend = QHBoxLayout()
        for index, (name, color) in enumerate(zip(names, Waveform.COLORS)):
            button = QToolButton()
            button.setText(f"● {name}")
            button.setCheckable(True)
            button.setChecked(True)
            button.setStyleSheet(
                f"QToolButton {{ color: {color}; background: #ffffff; "
                "font-weight: 600; }"
                f"QToolButton:checked {{ color: {color}; background: #ffffff; "
                f"border: 2px solid {color}; }}"
                "QToolButton:!checked { color: #75838c; background: #e8ecef; "
                "border-color: #cfd7dc; }"
            )
            button.toggled.connect(
                lambda checked, channel=index: wave.set_channel_visible(channel, checked)
            )
            legend.addWidget(button)
        legend.addStretch()
        layout.addLayout(legend)
        root.addWidget(box, 1)
        return wave


class SignalViewerWindow(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{PRODUCT_NAME} - Signal Viewer")
        self.resize(1180, 760)
        root = QVBoxLayout(self)
        self.status = QLabel("No signal loaded")
        self.status.setObjectName("muted")
        root.addWidget(self.status)
        self.plots = SignalPlotPanel()
        root.addWidget(self.plots, 1)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        root.addLayout(row)

    def set_cycle(
        self,
        status: str,
        channels: list[list[float]],
        sample_rate_hz: float | None,
        time_origin_samples: int,
        fault_boundary: str | None,
    ) -> None:
        self.status.setText(status)
        self.plots.set_cycle(channels, sample_rate_hz, time_origin_samples, fault_boundary)


@dataclass(frozen=True)
class _SignalCapture:
    channels: tuple[tuple[float, ...], ...]
    sample_rate_hz: float | None
    rated_frequency_hz: float | None
    config: dict[str, Any] | None
    created_at: datetime

    @property
    def sample_count(self) -> int:
        return len(self.channels[0]) if self.channels else 0

    @property
    def cycle_count(self) -> int:
        return max(1, (self.sample_count + SIGNAL_SAMPLES - 1) // SIGNAL_SAMPLES)

    @property
    def is_fault_capture(self) -> bool:
        return self.cycle_count >= 11


class SignalPage(QWidget):
    signal_requested = Signal()
    adc_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.analyzer = SignalAnalyzer()
        self.analysis_result: SignalAnalysisResult | None = None
        self.moving_analysis: tuple[MovingSignalAnalysis, ...] = ()
        self.analysis_window_index = 0
        self.analysis_window: SignalAnalysisWindow | None = None
        self.viewer_window: SignalViewerWindow | None = None
        self.captures: list[_SignalCapture] = []
        self.session_started_at = datetime.now()
        self.capture_index = -1
        self.cycle_index = 0

        root = QVBoxLayout(self)
        tools = QHBoxLayout()
        tools.addWidget(QLabel("Signal Viewer / Fault Analysis"))
        tools.addSpacing(16)
        tools.addWidget(QLabel("Session / Capture History"))
        self.capture_selector = QComboBox()
        self.capture_selector.setEnabled(False)
        self.capture_selector.setMinimumWidth(260)
        self.capture_selector.setMaxVisibleItems(20)
        self.capture_selector.setToolTip(
            f"Session started {self.session_started_at:%Y-%m-%d %H:%M:%S}"
        )
        self.capture_selector.currentIndexChanged.connect(self._select_capture)
        tools.addWidget(self.capture_selector)
        tools.addStretch()
        self.open_viewer = QPushButton("Open viewer")
        self.open_viewer.setEnabled(False)
        self.open_viewer.clicked.connect(self._show_viewer)
        tools.addWidget(self.open_viewer)
        self.get_button = QPushButton("Get signal")
        self.get_button.setEnabled(False)
        self.get_button.clicked.connect(self.signal_requested)
        tools.addWidget(self.get_button)
        self.adc_button = QPushButton("Get ADC")
        self.adc_button.setEnabled(False)
        self.adc_button.clicked.connect(self.adc_requested)
        tools.addWidget(self.adc_button)
        root.addLayout(tools)

        pages = QHBoxLayout()
        pages.addWidget(QLabel("Cycle pages"))
        self.cycle_buttons = QButtonGroup(self)
        self.cycle_buttons.setExclusive(True)
        self.cycle_button_layout = QHBoxLayout()
        pages.addLayout(self.cycle_button_layout)
        pages.addStretch()
        self.capture_status = QLabel("No capture loaded")
        self.capture_status.setObjectName("muted")
        pages.addWidget(self.capture_status)
        root.addLayout(pages)

        body = QHBoxLayout()
        body.setSpacing(8)
        self.plots = SignalPlotPanel()
        body.addWidget(self.plots, 1)
        self.analysis_summary = SignalAnalysisSummaryWidget()
        self.analysis_summary.details_requested.connect(self._show_analysis_details)
        body.addWidget(self.analysis_summary)
        root.addLayout(body, 1)

    def set_available(self, available: bool) -> None:
        self.get_button.setEnabled(available)
        self.adc_button.setEnabled(available)

    def set_adc(self, channels: list[list[float]]) -> None:
        if not hasattr(self, "adc_viewer"):
            self.adc_viewer = SignalViewerWindow(self)
            self.adc_viewer.setWindowTitle(f"{PRODUCT_NAME} - Raw ADC")
        self.adc_viewer.set_cycle("Raw ADC counts · company signal loader", channels, None, 0, None)
        self.adc_viewer.show()
        self.adc_viewer.raise_()

    def set_samples(
        self,
        channels: list[list[float]],
        sample_rate_hz: float | None = None,
        rated_frequency_hz: float | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        if len(channels) < 7 or not channels[0]:
            self._clear_analysis("Signal capture is incomplete")
            return
        lengths = {len(values) for values in channels if values}
        if len(lengths) != 1:
            self._clear_analysis("Signal channels have different sample counts")
            return
        if any(not math.isfinite(float(value)) for values in channels for value in values):
            self._clear_analysis("Signal capture contains a non-finite sample")
            return
        normalized = [tuple(float(value) for value in values) for values in channels[:10]]
        normalized.extend([tuple()] * (10 - len(normalized)))
        capture = _SignalCapture(
            tuple(normalized),
            sample_rate_hz,
            rated_frequency_hz,
            deepcopy(config) if config is not None else None,
            datetime.now(),
        )
        self.captures.append(capture)
        index = len(self.captures) - 1
        previous = self.captures[index - 1] if index else None
        interval = (
            f" · +{(capture.created_at - previous.created_at).total_seconds():.1f}s"
            if previous is not None
            else ""
        )
        kind = "Fault" if capture.is_fault_capture else "Signal"
        blocked = self.capture_selector.blockSignals(True)
        self.capture_selector.addItem(
            f"#{index + 1}  {capture.created_at:%H:%M:%S} · "
            f"{kind} · {capture.cycle_count} cycle(s){interval}"
        )
        self.capture_selector.setCurrentIndex(index)
        self.capture_selector.setEnabled(True)
        self.capture_selector.blockSignals(blocked)
        self._select_capture(index)

    def _select_capture(self, index: int) -> None:
        if not 0 <= index < len(self.captures):
            return
        self.capture_index = index
        if self.capture_selector.currentIndex() != index:
            blocked = self.capture_selector.blockSignals(True)
            self.capture_selector.setCurrentIndex(index)
            self.capture_selector.blockSignals(blocked)
        capture = self.captures[index]
        self._build_cycle_buttons(capture)
        self._build_moving_analysis(capture)
        self._select_cycle(0)
        self.open_viewer.setEnabled(True)

    def _build_cycle_buttons(self, capture: _SignalCapture) -> None:
        previous_group = self.cycle_buttons
        while self.cycle_button_layout.count():
            item = self.cycle_button_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        previous_group.deleteLater()
        self.cycle_buttons = QButtonGroup(self)
        self.cycle_buttons.setExclusive(True)
        for index in range(capture.cycle_count):
            button = QToolButton()
            if capture.is_fault_capture and index == 0:
                button.setText("−1")
                button.setToolTip("One cycle before fault")
            elif capture.is_fault_capture:
                button.setText(f"+{index}")
                button.setToolTip(f"Post-fault cycle {index}")
            else:
                button.setText("Live" if capture.cycle_count == 1 else str(index + 1))
            button.setCheckable(True)
            button.setFixedWidth(42)
            button.clicked.connect(
                lambda checked=False, selected=index: self._select_cycle(selected)
            )
            self.cycle_buttons.addButton(button)
            self.cycle_button_layout.addWidget(button)

    def _select_cycle(self, index: int) -> None:
        if not 0 <= self.capture_index < len(self.captures):
            return
        capture = self.captures[self.capture_index]
        if not 0 <= index < capture.cycle_count:
            return
        self.cycle_index = index
        button = self.cycle_buttons.buttons()[index]
        button.setChecked(True)
        start = index * SIGNAL_SAMPLES
        end = min(start + SIGNAL_SAMPLES, capture.sample_count)
        channels = [list(values[start:end]) for values in capture.channels]
        origin = (index - 1) * SIGNAL_SAMPLES if capture.is_fault_capture else start
        boundary = (
            "end"
            if capture.is_fault_capture and index == 0
            else "start"
            if capture.is_fault_capture and index == 1
            else None
        )
        status = self._status_text(capture, index, start, end)
        self.capture_status.setText(status)
        self.plots.set_cycle(channels, capture.sample_rate_hz, origin, boundary)
        self._select_analysis_window(index * 2)
        if self.viewer_window is not None:
            self.viewer_window.set_cycle(status, channels, capture.sample_rate_hz, origin, boundary)

    def _status_text(self, capture: _SignalCapture, index: int, start: int, end: int) -> str:
        capture_number = self.capture_index + 1
        previous = (
            self.captures[self.capture_index - 1] if self.capture_index > 0 else None
        )
        received = (
            f"received +{(capture.created_at - previous.created_at).total_seconds():.1f}s"
            if previous is not None
            else "session start"
        )
        if capture.is_fault_capture:
            page = "pre-fault" if index == 0 else f"post-fault +{index}"
            kind = "Fault"
        else:
            page = "live cycle" if capture.cycle_count == 1 else f"cycle {index + 1}"
            kind = "Signal"
        return (
            f"{kind} {capture_number}/{len(self.captures)} · {page} · "
            f"samples {start + 1}–{end} · {capture.created_at:%H:%M:%S} · {received}"
        )

    def _build_moving_analysis(self, capture: _SignalCapture) -> None:
        mapped = {
            name: values
            for name, values in zip(
                SIGNAL_CHANNEL_NAMES, capture.channels, strict=False
            )
            if values
        }
        try:
            self.moving_analysis = self.analyzer.analyze_moving(
                mapped,
                capture.sample_rate_hz,
                capture.rated_frequency_hz,
                capture.config,
                window_size=64,
                step_size=32,
            )
        except SignalAnalysisError as exc:
            self.moving_analysis = ()
            self._clear_analysis(str(exc))
            return
        if self.analysis_window is not None:
            self.analysis_window.set_moving_results(
                self.moving_analysis,
                capture.sample_rate_hz,
                SIGNAL_SAMPLES if capture.is_fault_capture else None,
            )

    def _select_analysis_window(self, index: int) -> None:
        if not self.moving_analysis:
            return
        self.analysis_window_index = min(max(index, 0), len(self.moving_analysis) - 1)
        window = self.moving_analysis[self.analysis_window_index]
        self.analysis_result = window.result
        capture = self.captures[self.capture_index]
        self.analysis_summary.set_result(
            self.analysis_result,
            self._analysis_window_text(capture, window),
        )
        if self.analysis_window is not None:
            self.analysis_window.select_window(self.analysis_window_index)

    def _analysis_window_text(
        self, capture: _SignalCapture, window: MovingSignalAnalysis
    ) -> str:
        if capture.sample_rate_hz:
            origin = SIGNAL_SAMPLES if capture.is_fault_capture else 0
            start_ms = (window.start_sample - origin) * 1000 / capture.sample_rate_hz
            end_ms = (window.end_sample - origin) * 1000 / capture.sample_rate_hz
            timing = (
                f"{start_ms:+.2f} to {end_ms:+.2f} ms"
                if capture.is_fault_capture
                else f"{start_ms:.2f} to {end_ms:.2f} ms"
            )
        else:
            timing = f"samples {window.start_sample + 1}–{window.end_sample}"
        return (
            f"Moving window {self.analysis_window_index + 1}/{len(self.moving_analysis)}"
            f" · {timing} · 32-sample step"
        )

    def _clear_analysis(self, message: str) -> None:
        self.analysis_result = None
        self.analysis_summary.clear(message)
        if self.analysis_window is not None:
            self.analysis_window.close()
            self.analysis_window.deleteLater()
            self.analysis_window = None

    def _show_viewer(self) -> None:
        if not 0 <= self.capture_index < len(self.captures):
            return
        if self.viewer_window is None:
            self.viewer_window = SignalViewerWindow(self)
        self._select_cycle(self.cycle_index)
        self.viewer_window.show()
        self.viewer_window.raise_()
        self.viewer_window.activateWindow()

    def _show_analysis_details(self) -> None:
        if self.analysis_result is None:
            return
        if self.analysis_window is None:
            self.analysis_window = SignalAnalysisWindow(self)
        capture = self.captures[self.capture_index]
        self.analysis_window.set_moving_results(
            self.moving_analysis,
            capture.sample_rate_hz,
            SIGNAL_SAMPLES if capture.is_fault_capture else None,
        )
        self.analysis_window.select_window(self.analysis_window_index)
        self.analysis_window.show()
        self.analysis_window.raise_()
        self.analysis_window.activateWindow()


class EventsPage(QWidget):
    load_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter events…")
        self.load_button = QPushButton("Load events")
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(self.load_requested)
        bar.addWidget(self.filter)
        bar.addWidget(self.load_button)
        root.addLayout(bar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Type", "Point", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)
        self.filter.textChanged.connect(self._filter)

    def set_available(self, available: bool) -> None:
        self.load_button.setEnabled(available)

    def set_events(self, records: list[EventRecord]) -> None:
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            for col, value in enumerate(
                (
                    record.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    record.kind,
                    record.point,
                    record.value,
                )
            ):
                self.table.setItem(row, col, QTableWidgetItem(value))
            if record.kind == "Counter" and record.value_bits == 16:
                self.table.item(row, 3).setToolTip("Device supplied a 16-bit counter value.")
        self._filter(self.filter.text())

    def _filter(self, text: str) -> None:
        needle = text.casefold()
        for row in range(self.table.rowCount()):
            visible = any(
                needle
                in (
                    self.table.item(row, col).text().casefold()
                    if self.table.item(row, col)
                    else ""
                )
                for col in range(4)
            )
            self.table.setRowHidden(row, not visible)
