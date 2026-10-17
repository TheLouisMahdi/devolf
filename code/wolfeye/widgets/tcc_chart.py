from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from wolfeye.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QPointF,
    QRectF,
    Qt,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    event_position,
)

from wolfeye.config_schema import TCC_TYPES
from wolfeye.numeric_schema import TIME
from wolfeye.widgets.numeric_editor import configure_numeric_editor, numeric_value, set_numeric_value


def calculate_trip_time_s(element: dict[str, Any], current_a: float) -> float | None:
    """Call the unchanged company WolfEye calculator; convert UI seconds to ms."""
    from wolfeye.services.beacheye import calculate_tcc_trip_ms

    curve_type = str(element.get("type", "TD"))
    if curve_type not in TCC_TYPES:
        return None
    pickup = int(element.get("pickup_a", 0))
    if not 0 < pickup <= 65535 or not math.isfinite(current_a):
        return None
    if not 0 <= current_a <= 65535:
        return None
    minimum = round(float(element.get("definite_min_time_s", 0)) * 1000)
    maximum = round(float(element.get("max_tripping_time_s", 120)) * 1000)
    trip_ms = calculate_tcc_trip_ms(
        TCC_TYPES.index(curve_type), pickup,
        float(element.get("time_multiplier", 1)), minimum, maximum,
        round(float(element.get("time_adder_s", 0)) * 1000),
        round(float(element.get("tripping_time_s", 0)) * 1000), int(current_a),
    )
    return trip_ms / 1000 if trip_ms is not None else None


@dataclass(frozen=True)
class CurveSpec:
    name: str
    element: dict[str, Any]
    color: QColor


def _axis_ticks(
    low: float,
    high: float,
    logarithmic: bool,
) -> list[tuple[float, bool, bool]]:
    """Return (value, major_grid, show_label) ticks for the current axis."""
    if high <= low:
        return [(low, True, True)]
    if not logarithmic:
        step = (high - low) / 5.0
        return [(low + step * index, True, True) for index in range(6)]

    low = max(low, 1e-12)
    high = max(high, low * 1.000001)
    span_decades = math.log10(high) - math.log10(low)
    start_exp = math.floor(math.log10(low))
    end_exp = math.ceil(math.log10(high))
    ticks: list[tuple[float, bool, bool]] = []
    for exponent in range(start_exp, end_exp + 1):
        decade = 10.0**exponent
        for multiple in range(1, 10):
            value = decade * multiple
            if not low <= value <= high:
                continue
            major = multiple == 1
            show_label = (
                major
                or span_decades <= 1.15
                or (span_decades <= 2.1 and multiple in (2, 5))
            )
            ticks.append((value, major, show_label))
    return ticks


class TccPlotWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("tccPlot")
        self.setMinimumSize(600, 420)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._curves: list[CurveSpec] = []

        self.min_current_a = 1.0
        self.max_current_a = 6000.0
        self.min_time_s = 0.01
        self.max_time_s = 120.0
        self.log_current = True
        self.log_time = True
        self._axis_signature: tuple[float, float, float, float, bool, bool] | None = None
        self._view_x_low = self.min_current_a
        self._view_x_high = self.max_current_a
        self._view_y_low = self.min_time_s
        self._view_y_high = self.max_time_s

    def set_curves(self, curves: list[CurveSpec]) -> None:
        self._curves = curves
        self.update()

    def set_axis_settings(
        self,
        min_current_a: float,
        max_current_a: float,
        min_time_s: float,
        max_time_s: float,
        log_current: bool,
        log_time: bool,
    ) -> None:
        if log_current:
            min_current_a = max(1e-9, min_current_a)
            max_current_a = max(min_current_a * 1.001, max_current_a)
        else:
            min_current_a = max(0.0, min_current_a)
            max_current_a = max(min_current_a + 1.0, max_current_a)
        if log_time:
            min_time_s = max(1e-9, min_time_s)
            max_time_s = max(min_time_s * 1.001, max_time_s)
        else:
            min_time_s = max(0.0, min_time_s)
            max_time_s = max(min_time_s + 0.001, max_time_s)

        signature = (
            float(min_current_a),
            float(max_current_a),
            float(min_time_s),
            float(max_time_s),
            bool(log_current),
            bool(log_time),
        )
        changed = signature != self._axis_signature
        self._axis_signature = signature
        (
            self.min_current_a,
            self.max_current_a,
            self.min_time_s,
            self.max_time_s,
            self.log_current,
            self.log_time,
        ) = signature
        if changed:
            self.reset_zoom()
        else:
            self.update()

    def reset_zoom(self) -> None:
        self._view_x_low = self.min_current_a
        self._view_x_high = self.max_current_a
        self._view_y_low = self.min_time_s
        self._view_y_high = self.max_time_s
        self.update()

    @staticmethod
    def _ratio(value: float, low: float, high: float, logarithmic: bool) -> float:
        value = min(high, max(low, value))
        if logarithmic:
            low = max(low, 1e-12)
            high = max(high, low * 1.000001)
            value = max(value, low)
            low_value = math.log10(low)
            return (math.log10(value) - low_value) / (math.log10(high) - low_value)
        if high <= low:
            return 0.0
        return (value - low) / (high - low)

    @staticmethod
    def _label(value: float) -> str:
        if value >= 1000:
            return f"{value / 1000:g}k"
        if value >= 1:
            return f"{value:g}"
        return f"{value:.3g}"

    def _plot_rect(self) -> QRectF:
        return QRectF(68, 24, max(80, self.width() - 92), max(80, self.height() - 82))

    @staticmethod
    def _zoom_axis(
        low: float,
        high: float,
        base_low: float,
        base_high: float,
        anchor: float,
        factor: float,
        logarithmic: bool,
    ) -> tuple[float, float]:
        anchor = min(1.0, max(0.0, anchor))
        if logarithmic:
            low_t = math.log10(max(low, 1e-12))
            high_t = math.log10(max(high, 1e-12))
            base_low_t = math.log10(max(base_low, 1e-12))
            base_high_t = math.log10(max(base_high, 1e-12))
        else:
            low_t, high_t = low, high
            base_low_t, base_high_t = base_low, base_high

        span = max(1e-12, high_t - low_t)
        base_span = max(1e-12, base_high_t - base_low_t)
        new_span = min(base_span, max(base_span * 1e-6, span * factor))
        center = low_t + anchor * span
        new_low = center - anchor * new_span
        new_high = new_low + new_span

        if new_low < base_low_t:
            new_high += base_low_t - new_low
            new_low = base_low_t
        if new_high > base_high_t:
            new_low -= new_high - base_high_t
            new_high = base_high_t
        new_low = max(base_low_t, new_low)
        new_high = min(base_high_t, new_high)

        if logarithmic:
            return 10.0**new_low, 10.0**new_high
        return new_low, new_high

    def zoom(
        self,
        factor: float,
        x_anchor: float = 0.5,
        y_anchor: float = 0.5,
        *,
        x_axis: bool = True,
        y_axis: bool = True,
    ) -> None:
        if factor <= 0.0:
            return
        if x_axis:
            self._view_x_low, self._view_x_high = self._zoom_axis(
                self._view_x_low,
                self._view_x_high,
                self.min_current_a,
                self.max_current_a,
                x_anchor,
                factor,
                self.log_current,
            )
        if y_axis:
            self._view_y_low, self._view_y_high = self._zoom_axis(
                self._view_y_low,
                self._view_y_high,
                self.min_time_s,
                self.max_time_s,
                y_anchor,
                factor,
                self.log_time,
            )
        self.update()

    def zoom_in(self) -> None:
        self.zoom(0.75)

    def zoom_out(self) -> None:
        self.zoom(1.0 / 0.75)

    def wheelEvent(self, event) -> None:  # noqa: N802
        plot = self._plot_rect()
        position = event_position(event)
        if not plot.contains(position) or event.angleDelta().y() == 0:
            super().wheelEvent(event)
            return

        x_anchor = (position.x() - plot.left()) / plot.width()
        y_anchor = (plot.bottom() - position.y()) / plot.height()
        factor = 0.80 if event.angleDelta().y() > 0 else 1.25
        modifiers = event.modifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        x_axis = shift and not control
        y_axis = control and not shift
        if not x_axis and not y_axis:
            x_axis = True
            y_axis = True
        self.zoom(
            factor,
            x_anchor,
            y_anchor,
            x_axis=x_axis,
            y_axis=y_axis,
        )
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._plot_rect().contains(event_position(event)):
            self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        plot = self._plot_rect()
        painter.fillRect(plot, QColor("#f8fbfc"))

        x_low, x_high = self._view_x_low, self._view_x_high
        y_low, y_high = self._view_y_low, self._view_y_high

        painter.setFont(self.font())
        major_grid_pen = QPen(QColor("#cbd8de"), 1)
        minor_grid_pen = QPen(QColor("#e8eef1"), 1)
        text_pen = QPen(QColor("#526773"), 1)

        for value, major, show_label in _axis_ticks(
            x_low, x_high, self.log_current
        ):
            ratio = self._ratio(value, x_low, x_high, self.log_current)
            x = plot.left() + ratio * plot.width()
            painter.setPen(major_grid_pen if major else minor_grid_pen)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            if show_label:
                painter.setPen(text_pen)
                painter.drawText(
                    QRectF(x - 34, plot.bottom() + 6, 68, 18),
                    Qt.AlignmentFlag.AlignHCenter,
                    self._label(value),
                )

        for value, major, show_label in _axis_ticks(
            y_low, y_high, self.log_time
        ):
            ratio = self._ratio(value, y_low, y_high, self.log_time)
            y = plot.bottom() - ratio * plot.height()
            painter.setPen(major_grid_pen if major else minor_grid_pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            if show_label:
                painter.setPen(text_pen)
                painter.drawText(
                    QRectF(4, y - 9, 56, 18),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    self._label(value),
                )

        painter.setPen(QPen(QColor("#718792"), 1.2))
        painter.drawRect(plot)
        painter.setPen(QPen(QColor("#244556"), 1))
        x_axis_title = (
            "Current (A) · Log10" if self.log_current else "Current (A) · Linear"
        )
        painter.drawText(
            QRectF(plot.left(), self.height() - 27, plot.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            x_axis_title,
        )
        painter.save()
        painter.translate(18, plot.center().y())
        painter.rotate(-90)
        y_axis_title = (
            "Trip time (s) · Log10" if self.log_time else "Trip time (s) · Linear"
        )
        painter.drawText(
            QRectF(-plot.height() / 2, -10, plot.height(), 20),
            Qt.AlignmentFlag.AlignCenter,
            y_axis_title,
        )
        painter.restore()

        painter.save()
        painter.setClipRect(plot.adjusted(1, 1, -1, -1))
        for curve in self._curves:
            pickup = max(1.0, float(curve.element.get("pickup_a", 1.0)))
            inverse_time = str(curve.element.get("type", "TD")) != "TD"
            minimum_multiplier = (
                max(1.0, float(curve.element.get("min_current_multiplier", 1.0)))
                if inverse_time
                else 1.0
            )
            start = max(x_low, pickup * minimum_multiplier)
            curve_high = x_high
            if inverse_time and bool(curve.element.get("max_mode", False)):
                curve_high = min(
                    curve_high,
                    pickup
                    * max(
                        1.1,
                        float(curve.element.get("max_current_multiplier", 5.0)),
                    ),
                )
            if start >= curve_high:
                continue
            path = QPainterPath()
            started = False
            samples = 360
            for index in range(samples):
                fraction = index / (samples - 1)
                if self.log_current:
                    current = 10 ** (
                        math.log10(start)
                        + fraction * (math.log10(curve_high) - math.log10(start))
                    )
                else:
                    current = start + fraction * (curve_high - start)
                trip = calculate_trip_time_s(curve.element, current)
                if trip is None:
                    continue
                floor = y_low * 1.02 if self.log_time else 0.0
                plotted_trip = max(floor, min(y_high, trip))
                x = (
                    plot.left()
                    + self._ratio(current, x_low, x_high, self.log_current)
                    * plot.width()
                )
                y = (
                    plot.bottom()
                    - self._ratio(plotted_trip, y_low, y_high, self.log_time)
                    * plot.height()
                )
                if started:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
                    started = True
            painter.setPen(QPen(curve.color, 2.2))
            painter.drawPath(path)
        painter.restore()

        legend_x = plot.left() + 10
        legend_y = plot.top() + 8
        for curve in self._curves:
            painter.setPen(QPen(curve.color, 3))
            painter.drawLine(
                QPointF(legend_x, legend_y + 7),
                QPointF(legend_x + 22, legend_y + 7),
            )
            painter.setPen(QPen(QColor("#263b46"), 1))
            painter.drawText(
                QRectF(legend_x + 28, legend_y, 92, 16), curve.name
            )
            legend_x += 120


class TccChartDialog(QDialog):
    _COLORS = (
        "#eb4034",
        "#dfa81b",
        "#0a782d",
        "#0732f2",
        "#eb2fd8",
        "#828182",
    )

    def __init__(
        self,
        title: str,
        names: tuple[str, ...],
        elements: list[dict[str, Any]],
        selected_index: int,
        view_settings: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tccDialog")
        self.setWindowTitle(f"{title} · Protection Curve")
        self.resize(980, 650)
        self.setMinimumSize(850, 600)
        self._names = names
        self._elements = elements
        self._view_settings = view_settings
        self._is_sef = all(name.startswith("SEF") for name in names)
        self._loading_element = False

        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("tccTitle")
        heading.addWidget(title_label)
        heading.addStretch()
        reference = QLabel("Company ANSI / IEC TCC model")
        reference.setObjectName("muted")
        heading.addWidget(reference)
        root.addLayout(heading)

        body = QHBoxLayout()
        sidebar = QWidget()
        sidebar.setObjectName("tccSidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.addWidget(QLabel("Show Elements"))
        self.elements_list = QListWidget()
        self.elements_list.setMaximumHeight(145)
        for name, element in zip(names, elements):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if bool(element.get("enabled"))
                else Qt.CheckState.Unchecked
            )
            self.elements_list.addItem(item)
        selected = max(0, min(selected_index, len(elements) - 1))
        if elements and not bool(elements[selected].get("enabled")):
            selected = next(
                (
                    index
                    for index in range(len(elements) - 1, -1, -1)
                    if bool(elements[index].get("enabled"))
                ),
                -1,
            )
        self.elements_list.setCurrentRow(selected)
        side_layout.addWidget(self.elements_list)

        side_layout.addWidget(QLabel("Element setting"))
        self.element_form = QFormLayout()
        self.curve_type = QComboBox()
        self.curve_type.addItems(TCC_TYPES)
        self.element_form.addRow("TCC type", self.curve_type)
        self.pickup = QSpinBox()
        self.pickup.setRange(1, 65535)
        self.pickup.setSuffix(" A")
        self.element_form.addRow("Pickup", self.pickup)
        self.time_multiplier = QDoubleSpinBox()
        self.time_multiplier.setRange(0.01, 15.0)
        self.time_multiplier.setDecimals(2)
        self.element_form.addRow("Time multiplier", self.time_multiplier)
        self.element_min_current = QDoubleSpinBox()
        self.element_min_current.setRange(1.0, 5.0)
        self.element_min_current.setDecimals(2)
        self.element_form.addRow("Min. current mult.", self.element_min_current)
        self.max_mode = QCheckBox()
        self.element_form.addRow("Max. current mode", self.max_mode)
        self.element_max_current = QDoubleSpinBox()
        self.element_max_current.setRange(1.1, 10.0)
        self.element_max_current.setDecimals(2)
        self.element_form.addRow("Max. current mult.", self.element_max_current)
        self.element_min_time = QDoubleSpinBox()
        self.element_min_time.setRange(0.0, 10.0)
        self.element_min_time.setDecimals(2)
        self.element_min_time.setSuffix(" s")
        self.element_form.addRow("Definite min.", self.element_min_time)
        self.trip_time = QDoubleSpinBox()
        self.trip_time.setRange(0.0, 300.0)
        self.trip_time.setDecimals(2)
        self.trip_time.setSuffix(" s")
        self.element_form.addRow("Trip time", self.trip_time)
        self.max_trip_time = QDoubleSpinBox()
        self.max_trip_time.setRange(1.0, 120.0)
        self.max_trip_time.setDecimals(2)
        self.max_trip_time.setSuffix(" s")
        self.element_form.addRow("Max. trip time", self.max_trip_time)
        self.time_adder = QDoubleSpinBox()
        self.time_adder.setRange(0.0, 2.0)
        self.time_adder.setDecimals(2)
        self.time_adder.setSuffix(" s")
        self.element_form.addRow("Time adder", self.time_adder)
        self.reset_time = QDoubleSpinBox()
        self.reset_time.setRange(0.0, 2.0)
        self.reset_time.setDecimals(2)
        self.reset_time.setSuffix(" s")
        self.element_form.addRow("Reset time", self.reset_time)
        for control, field in (
            (self.pickup, "pickup_a"),
            (self.time_multiplier, "time_multiplier"),
            (self.element_min_current, "min_current_multiplier"),
            (self.element_max_current, "max_current_multiplier"),
            (self.element_min_time, "definite_min_time_s"),
            (self.trip_time, "tripping_time_s"),
            (self.max_trip_time, "max_tripping_time_s"),
            (self.time_adder, "time_adder_s"),
            (self.reset_time, "reset_time_s"),
        ):
            configure_numeric_editor(control, f"protection.groups.0.oc.elements.0.{field}")
        side_layout.addLayout(self.element_form)

        controls = QFormLayout()
        self.test_point = QSpinBox()
        self.test_point.setRange(0, 65535)
        self.test_point.setValue(int(view_settings.get("test_point_a", 100)))
        self.test_point.setSuffix(" A")
        controls.addRow("Test point", self.test_point)
        self.view_min_current = QSpinBox()
        self.view_min_current.setRange(1, 65534)
        self.view_min_current.setValue(int(view_settings.get("min_current_a", 1)))
        self.view_min_current.setSuffix(" A")
        controls.addRow("Min. current", self.view_min_current)
        self.view_max_current = QSpinBox()
        self.view_max_current.setRange(2, 65535)
        self.view_max_current.setValue(int(view_settings.get("max_current_a", 6000)))
        self.view_max_current.setSuffix(" A")
        controls.addRow("Max. current", self.view_max_current)

        self.current_scale = QComboBox()
        self.current_scale.addItem("Log10", True)
        self.current_scale.addItem("Linear", False)
        self.current_scale.setCurrentIndex(
            0 if bool(view_settings.get("log_current_axis", True)) else 1
        )
        controls.addRow("Current scale", self.current_scale)

        self.view_min_time = QDoubleSpinBox()
        self.view_min_time.setRange(0.001, TIME.maximum - 0.001)
        self.view_min_time.setDecimals(3)
        self.view_min_time.setValue(float(view_settings.get("min_time_s", 0.01)))
        self.view_min_time.setSuffix(" s")
        controls.addRow("Min. time", self.view_min_time)
        self.view_max_time = QDoubleSpinBox()
        self.view_max_time.setRange(0.002, TIME.maximum)
        self.view_max_time.setDecimals(3)
        self.view_max_time.setValue(float(view_settings.get("max_time_s", 120.0)))
        self.view_max_time.setSuffix(" s")
        controls.addRow("Max. time", self.view_max_time)

        self.time_scale = QComboBox()
        self.time_scale.addItem("Log10", True)
        self.time_scale.addItem("Linear", False)
        self.time_scale.setCurrentIndex(
            0 if bool(view_settings.get("log_time_axis", True)) else 1
        )
        controls.addRow("Time scale", self.time_scale)
        side_layout.addLayout(controls)
        self.trip_result = QLabel("Trip time: —")
        self.trip_result.setObjectName("tccResult")
        side_layout.addWidget(self.trip_result)
        body.addWidget(sidebar, 0)

        plot_panel = QWidget()
        plot_layout = QVBoxLayout(plot_panel)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(4)
        zoom_row = QHBoxLayout()
        zoom_hint = QLabel("Wheel: zoom both · Shift+Wheel: X · Ctrl+Wheel: Y · Double-click: reset")
        zoom_hint.setObjectName("muted")
        zoom_row.addWidget(zoom_hint)
        zoom_row.addStretch()
        zoom_in_button = QPushButton("Zoom +")
        zoom_out_button = QPushButton("Zoom −")
        zoom_reset_button = QPushButton("Reset zoom")
        zoom_row.addWidget(zoom_in_button)
        zoom_row.addWidget(zoom_out_button)
        zoom_row.addWidget(zoom_reset_button)
        plot_layout.addLayout(zoom_row)

        self.plot = TccPlotWidget()
        plot_layout.addWidget(self.plot, 1)
        body.addWidget(plot_panel, 1)
        root.addLayout(body, 1)

        zoom_in_button.clicked.connect(self.plot.zoom_in)
        zoom_out_button.clicked.connect(self.plot.zoom_out)
        zoom_reset_button.clicked.connect(self.plot.reset_zoom)

        self.elements_list.itemChanged.connect(self._refresh)
        self.elements_list.currentRowChanged.connect(self._selection_changed)
        self.curve_type.currentTextChanged.connect(self._update_selected_element)
        self.pickup.valueChanged.connect(self._update_selected_element)
        self.time_multiplier.valueChanged.connect(self._update_selected_element)
        self.element_min_current.valueChanged.connect(self._update_selected_element)
        self.max_mode.toggled.connect(self._update_selected_element)
        self.element_max_current.valueChanged.connect(self._update_selected_element)
        self.element_min_time.valueChanged.connect(self._update_selected_element)
        self.trip_time.valueChanged.connect(self._update_selected_element)
        self.max_trip_time.valueChanged.connect(self._update_selected_element)
        self.time_adder.valueChanged.connect(self._update_selected_element)
        self.reset_time.valueChanged.connect(self._update_selected_element)
        self.test_point.valueChanged.connect(self._refresh)
        self.view_min_current.valueChanged.connect(self._refresh)
        self.view_max_current.valueChanged.connect(self._refresh)
        self.current_scale.currentIndexChanged.connect(self._refresh)
        self.view_min_time.valueChanged.connect(self._refresh)
        self.view_max_time.valueChanged.connect(self._refresh)
        self.time_scale.currentIndexChanged.connect(self._refresh)
        self._load_selected_element()
        self._refresh()

    def _selection_changed(self, _row: int) -> None:
        self._load_selected_element()
        self._refresh()

    @staticmethod
    def _set_control_value(widget: QWidget, value: Any) -> None:
        blocked = widget.blockSignals(True)
        try:
            if isinstance(widget, QComboBox):
                widget.setCurrentText(str(value))
            elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                set_numeric_value(widget, value)
        finally:
            widget.blockSignals(blocked)

    def _load_selected_element(self) -> None:
        selected = self.elements_list.currentRow()
        if not 0 <= selected < len(self._elements):
            self._update_editor_visibility()
            return
        self._loading_element = True
        try:
            element = self._elements[selected]
            self._set_control_value(self.curve_type, element.get("type", "TD"))
            self._set_control_value(self.pickup, element.get("pickup_a", 1))
            self._set_control_value(
                self.time_multiplier, element.get("time_multiplier", 1.0)
            )
            self._set_control_value(
                self.element_min_current, element.get("min_current_multiplier", 1.0)
            )
            blocked = self.max_mode.blockSignals(True)
            self.max_mode.setChecked(bool(element.get("max_mode", False)))
            self.max_mode.blockSignals(blocked)
            self._set_control_value(
                self.element_max_current,
                element.get("max_current_multiplier", 5.0),
            )
            self._set_control_value(
                self.element_min_time, element.get("definite_min_time_s", 0.0)
            )
            self._set_control_value(
                self.trip_time, element.get("tripping_time_s", 0.0)
            )
            self._set_control_value(
                self.max_trip_time, element.get("max_tripping_time_s", 120.0)
            )
            self._set_control_value(
                self.time_adder, element.get("time_adder_s", 0.0)
            )
            self._set_control_value(
                self.reset_time, element.get("reset_time_s", 0.0)
            )
            self._update_editor_visibility()
        finally:
            self._loading_element = False

    def _set_form_row_visible(self, widget: QWidget, visible: bool) -> None:
        label = self.element_form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)
        widget.setVisible(visible)

    def _update_editor_visibility(self) -> None:
        selected = self.elements_list.currentRow()
        if selected < 0:
            for widget in (
                self.curve_type,
                self.pickup,
                self.time_multiplier,
                self.element_min_current,
                self.max_mode,
                self.element_max_current,
                self.element_min_time,
                self.trip_time,
                self.max_trip_time,
                self.time_adder,
                self.reset_time,
            ):
                self._set_form_row_visible(widget, False)
            return

        highset = len(self._elements) > 2 and (selected + 1) % 3 == 0
        if self._is_sef:
            self._set_form_row_visible(self.curve_type, False)
            self._set_form_row_visible(self.pickup, True)
            for widget in (
                self.time_multiplier,
                self.element_min_current,
                self.max_mode,
                self.element_max_current,
                self.element_min_time,
                self.max_trip_time,
                self.time_adder,
            ):
                self._set_form_row_visible(widget, False)
            self._set_form_row_visible(self.trip_time, True)
            self._set_form_row_visible(self.reset_time, True)
            return
        curve_type = self.curve_type.currentText()
        definite_time = curve_type == "TD"
        inverse_time = not highset and not definite_time
        fast_trip = len(self._elements) > 2 and selected % 3 == 1
        self._set_form_row_visible(self.curve_type, not highset)
        self._set_form_row_visible(self.pickup, True)
        self._set_form_row_visible(self.trip_time, highset or definite_time)
        for widget in (
            self.time_multiplier,
            self.element_min_current,
            self.element_min_time,
            self.max_trip_time,
            self.time_adder,
        ):
            self._set_form_row_visible(widget, inverse_time)
        self._set_form_row_visible(self.max_mode, inverse_time and fast_trip)
        self._set_form_row_visible(
            self.element_max_current,
            inverse_time and fast_trip and self.max_mode.isChecked(),
        )
        self._set_form_row_visible(
            self.reset_time,
            not highset and (definite_time or curve_type.startswith("IEC ")),
        )

    def _update_selected_element(self, *_args) -> None:
        if self._loading_element:
            return
        selected = self.elements_list.currentRow()
        if not 0 <= selected < len(self._elements):
            return
        element = self._elements[selected]
        element.update(
            type=self.curve_type.currentText(),
            pickup_a=numeric_value(self.pickup),
            time_multiplier=numeric_value(self.time_multiplier),
            min_current_multiplier=numeric_value(self.element_min_current),
            max_mode=self.max_mode.isChecked(),
            max_current_multiplier=numeric_value(self.element_max_current),
            definite_min_time_s=numeric_value(self.element_min_time),
            tripping_time_s=numeric_value(self.trip_time),
            max_tripping_time_s=numeric_value(self.max_trip_time),
            time_adder_s=numeric_value(self.time_adder),
            reset_time_s=numeric_value(self.reset_time),
        )
        self._update_editor_visibility()
        self._refresh()

    def _refresh(self, *_args) -> None:
        curves: list[CurveSpec] = []
        for index, (name, element) in enumerate(zip(self._names, self._elements)):
            item = self.elements_list.item(index)
            enabled = item.checkState() == Qt.CheckState.Checked
            element["enabled"] = enabled
            if enabled:
                curves.append(CurveSpec(name, element, QColor(self._COLORS[index % len(self._COLORS)])))

        selected = self.elements_list.currentRow()
        if (
            0 <= selected < self.elements_list.count()
            and self.elements_list.item(selected).checkState() != Qt.CheckState.Checked
        ):
            self.elements_list.setCurrentRow(-1)
            self._update_editor_visibility()

        log_current = bool(self.current_scale.currentData())
        log_time = bool(self.time_scale.currentData())

        min_current = float(self.view_min_current.value())
        max_current = max(min_current + 1.0, float(self.view_max_current.value()))
        min_time = float(self.view_min_time.value())
        max_time = max(
            min_time * 1.001 if log_time else min_time + 0.001,
            float(self.view_max_time.value()),
        )

        self.plot.set_axis_settings(
            min_current,
            max_current,
            min_time,
            max_time,
            log_current,
            log_time,
        )
        self.plot.set_curves(curves)

        self._view_settings.update(
            test_point_a=self.test_point.value(),
            min_current_a=self.view_min_current.value(),
            max_current_a=self.view_max_current.value(),
            min_time_s=self.view_min_time.value(),
            max_time_s=self.view_max_time.value(),
            log_current_axis=log_current,
            log_time_axis=log_time,
        )
        selected = self.elements_list.currentRow()
        if 0 <= selected < len(self._elements):
            trip = calculate_trip_time_s(self._elements[selected], self.test_point.value())
            self.trip_result.setText(
                f"Trip time: {trip * 1000:.0f} ms" if trip is not None else "Trip time: —"
            )

