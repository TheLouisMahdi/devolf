from __future__ import annotations

from wolfeye.branding import PRODUCT_NAME
from wolfeye.qt import (
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    Signal,
)

from wolfeye.services.signal_analysis import (
    MovingSignalAnalysis,
    Phasor,
    SignalAnalysisResult,
)


class SignalAnalysisSummaryWidget(QGroupBox):
    details_requested = Signal()

    def __init__(self) -> None:
        super().__init__("Signal Analysis Summary")
        self.setMinimumWidth(285)
        self.setMaximumWidth(355)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 9)
        layout.setSpacing(6)
        self.state = QLabel("No signal loaded")
        self.state.setObjectName("muted")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        self.values: dict[str, QLabel] = {}
        rows = (
            ("Capture", "capture"),
            ("Voltage RMS", "voltage_rms"),
            ("Current RMS", "current_rms"),
            ("Sequences", "sequences"),
            ("Power quality", "quality"),
            ("Directional", "directional"),
            ("Protection", "protection"),
        )
        for row, (title, key) in enumerate(rows):
            label = QLabel(title)
            label.setObjectName("metricTitle")
            value = QLabel("N/A")
            value.setWordWrap(True)
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
            self.values[key] = value
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch()

        self.details_button = QPushButton("Analysis Details")
        self.details_button.setEnabled(False)
        self.details_button.clicked.connect(self.details_requested)
        layout.addWidget(self.details_button)

    def clear(self, message: str = "No signal loaded") -> None:
        self.state.setText(message)
        for value in self.values.values():
            value.setText("N/A")
        self.details_button.setEnabled(False)

    def set_result(
        self, result: SignalAnalysisResult, window_text: str | None = None
    ) -> None:
        self.state.setText(
            window_text or f"{result.sample_count} samples · analysis ready"
        )
        sample_rate = (
            f"{result.sample_rate_hz:.0f} Sa/s"
            if result.sample_rate_hz is not None
            else "Sample rate N/A"
        )
        self.values["capture"].setText(
            f"{sample_rate}\nPhase sequence {result.phase_sequence}"
        )
        self.values["voltage_rms"].setText(
            _channel_values(result, ("Va", "Vb", "Vc"), "V")
        )
        self.values["current_rms"].setText(
            _channel_values(result, ("Ia", "Ib", "Ic", "In"), "A")
        )
        self.values["sequences"].setText(
            _sequence_values(result, ("V1", "V2", "V0"), "V")
            + "\n"
            + _sequence_values(result, ("I1", "I2", "I0"), "A")
        )
        if result.power_quality_sample_count:
            self.values["quality"].setText(
                f"200 ms / {result.power_quality_sample_count} samples\n"
                f"THD-V max {_number(result.voltage_thd_percent, '%')} · "
                f"THD-I {_number(result.current_thd_percent, '%')}"
            )
        else:
            self.values["quality"].setText(
                "N/A · requires a trailing 200 ms window\n"
                "Harmonics, spectrum and THD are withheld"
            )
        self.values["directional"].setText(
            " · ".join(
                f"{name} {value.state}" for name, value in result.directional.items()
            )
        )
        self.values["protection"].setText(
            " · ".join(
                f"{name} {value.state}" for name, value in result.protection.items()
            )
        )
        self.details_button.setEnabled(True)


class SignalAnalysisWindow(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{PRODUCT_NAME} - Signal Analysis")
        self.resize(900, 620)
        root = QVBoxLayout(self)
        window_row = QHBoxLayout()
        window_row.addWidget(QLabel("Moving analysis window"))
        self.window_selector = QComboBox()
        self.window_selector.setMinimumWidth(420)
        self.window_selector.currentIndexChanged.connect(self._show_selected_window)
        window_row.addWidget(self.window_selector)
        window_row.addWidget(QLabel("64 samples · 32-sample step · 50% overlap"))
        window_row.addStretch()
        root.addLayout(window_row)
        self.moving_results: tuple[MovingSignalAnalysis, ...] = ()
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.overview = self._table(("Metric", "Value"))
        self.phasors = self._table(("Signal", "RMS", "Phase", "Real", "Imag"))
        self.sequences = self._table(("Quantity", "Magnitude", "Phase", "Real", "Imag"))
        self.harmonics = self._table(
            ("Signal", "Harmonic", "Magnitude", "% H1", "Phase")
        )
        self.directional = self._table(
            (
                "Element",
                "U pol",
                "I op",
                "Angle",
                "Torque",
                "In cos θ",
                "In sin θ",
                "Direction",
            )
        )
        self.protection = self._table(
            ("Element", "Quantity", "Pickup", "Multiple", "State")
        )
        for table, title in (
            (self.overview, "Overview"),
            (self.phasors, "Phasors"),
            (self.sequences, "Sequences"),
            (self.harmonics, "Harmonics"),
            (self.directional, "Directional"),
            (self.protection, "Protection"),
        ):
            self.tabs.addTab(table, title)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def set_moving_results(
        self,
        results: tuple[MovingSignalAnalysis, ...],
        sample_rate_hz: float | None,
        fault_sample_index: int | None = None,
    ) -> None:
        self.moving_results = results
        self.window_selector.blockSignals(True)
        self.window_selector.clear()
        for index, window in enumerate(results):
            self.window_selector.addItem(
                _moving_window_label(
                    index,
                    len(results),
                    window,
                    sample_rate_hz,
                    fault_sample_index,
                )
            )
        self.window_selector.blockSignals(False)
        self.window_selector.setEnabled(bool(results))
        if results:
            self.window_selector.setCurrentIndex(0)
            self.set_result(results[0].result)

    def select_window(self, index: int) -> None:
        if not 0 <= index < len(self.moving_results):
            return
        if self.window_selector.currentIndex() == index:
            self.set_result(self.moving_results[index].result)
        else:
            self.window_selector.setCurrentIndex(index)

    def _show_selected_window(self, index: int) -> None:
        if 0 <= index < len(self.moving_results):
            self.set_result(self.moving_results[index].result)

    def set_result(self, result: SignalAnalysisResult) -> None:
        overview_rows = [
            ("Phase sequence", result.phase_sequence),
            (
                "Sample rate",
                f"{result.sample_rate_hz:.1f} Sa/s"
                if result.sample_rate_hz is not None
                else "N/A",
            ),
            ("Sample count", str(result.sample_count)),
            (
                "Power-quality window",
                f"200 ms / {result.power_quality_sample_count} samples"
                if result.power_quality_sample_count
                else "N/A - requires 200 ms of samples",
            ),
            ("Voltage THD maximum", _number(result.voltage_thd_percent, "%")),
            (
                "Current THD diagnostic",
                _number(result.current_thd_percent, "%"),
            ),
            (
                "Current TDD",
                _number(result.current_tdd_percent, "%")
                if result.current_tdd_percent is not None
                else "N/A - peak demand unavailable",
            ),
        ]
        for name in ("Va", "Vb", "Vc", "Ia", "Ib", "Ic", "In"):
            channel = result.channels.get(name)
            if channel is None:
                continue
            overview_rows.extend(
                (
                    (f"{name} true RMS", _number(channel.true_rms, channel.unit)),
                    (
                        f"{name} fundamental RMS",
                        _number(
                            channel.fundamental.magnitude
                            if channel.fundamental
                            else None,
                            channel.unit,
                        ),
                    ),
                    (
                        f"{name} angle",
                        _number(
                            channel.fundamental.angle_deg
                            if channel.fundamental
                            else None,
                            "°",
                        ),
                    ),
                )
            )
        overview_rows.extend(
            (label, _number(value, "°"))
            for label, value in result.angle_differences.items()
        )
        self._fill(self.overview, overview_rows)

        phasor_rows = []
        for name in ("Va", "Vb", "Vc", "Ia", "Ib", "Ic", "In"):
            channel = result.channels.get(name)
            if channel is None:
                continue
            phasor_rows.append(_phasor_row(name, channel.fundamental, channel.unit))
        self._fill(self.phasors, phasor_rows)

        sequence_rows = [
            _phasor_row(
                name, result.sequences.get(name), "V" if name[0] == "V" else "A"
            )
            for name in ("V1", "V2", "V0", "I1", "I2", "I0")
        ]
        sequence_rows.extend(
            (
                ("I2/I1", _number(result.i2_i1_percent, "%"), "", "", ""),
                (
                    "Measured In - 3I0",
                    _number(result.measured_in_difference, "A"),
                    "",
                    "",
                    "",
                ),
                _phasor_row(
                    "Measured In",
                    result.channels.get("In").fundamental
                    if "In" in result.channels
                    else None,
                    "A",
                ),
                _phasor_row("Calculated 3I0", result.residual_current, "A"),
                _phasor_row("Calculated 3V0", result.residual_voltage, "V"),
            )
        )
        self._fill(self.sequences, sequence_rows)

        harmonic_rows = []
        for name in ("Va", "Vb", "Vc", "Ia", "Ib", "Ic", "In"):
            channel = result.channels.get(name)
            if channel is None:
                continue
            for order, harmonic in channel.harmonics.items():
                phasor = harmonic.phasor
                harmonic_rows.append(
                    (
                        name,
                        f"H{order}",
                        _number(phasor.magnitude if phasor else None, channel.unit),
                        _number(harmonic.percent_of_fundamental, "%"),
                        _number(phasor.angle_deg if phasor else None, "°"),
                    )
                )
        if not harmonic_rows:
            harmonic_rows.append(
                (
                    "N/A",
                    "Requires a trailing 200 ms window",
                    "",
                    "",
                    "",
                )
            )
        self._fill(self.harmonics, harmonic_rows)

        self._fill(
            self.directional,
            [
                (
                    name,
                    value.polarising,
                    value.operating,
                    _number(value.angle_deg, "°"),
                    _number(value.torque_angle_deg, "°"),
                    _number(value.in_cos_theta, "A"),
                    _number(value.in_sin_theta, "A"),
                    value.state,
                )
                for name, value in result.directional.items()
            ],
        )
        self._fill(
            self.protection,
            [
                (
                    name,
                    _number(value.quantity, value.unit),
                    _number(value.pickup, value.unit),
                    _number(value.multiple, "x", 3),
                    value.state,
                )
                for name, value in result.protection.items()
            ],
        )

    @staticmethod
    def _table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return table

    @staticmethod
    def _fill(table: QTableWidget, rows) -> None:
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()


def _number(value: float | None, unit: str = "", precision: int = 2) -> str:
    if value is None:
        return "N/A"
    suffix = f" {unit}" if unit else ""
    return f"{value:.{precision}f}{suffix}"


def _moving_window_label(
    index: int,
    count: int,
    window: MovingSignalAnalysis,
    sample_rate_hz: float | None,
    fault_sample_index: int | None,
) -> str:
    samples = f"samples {window.start_sample + 1}–{window.end_sample}"
    if not sample_rate_hz:
        return f"Window {index + 1}/{count} · {samples}"
    origin = fault_sample_index or 0
    start_ms = (window.start_sample - origin) * 1000 / sample_rate_hz
    end_ms = (window.end_sample - origin) * 1000 / sample_rate_hz
    timing = (
        f"{start_ms:+.2f} to {end_ms:+.2f} ms"
        if fault_sample_index is not None
        else f"{start_ms:.2f} to {end_ms:.2f} ms"
    )
    return f"Window {index + 1}/{count} · {timing} · {samples}"


def _channel_values(
    result: SignalAnalysisResult, names: tuple[str, ...], unit: str
) -> str:
    return (
        "  ".join(
            f"{name} {_number(result.channels[name].true_rms, unit)}"
            for name in names
            if name in result.channels
        )
        or "N/A"
    )


def _sequence_values(
    result: SignalAnalysisResult, names: tuple[str, ...], unit: str
) -> str:
    return (
        "  ".join(
            f"{name} {_number(result.sequences[name].magnitude, unit)}"
            for name in names
            if name in result.sequences
        )
        or "N/A"
    )


def _phasor_row(name: str, phasor: Phasor | None, unit: str) -> tuple[str, ...]:
    return (
        name,
        _number(phasor.magnitude if phasor else None, unit),
        _number(phasor.angle_deg if phasor else None, "°"),
        _number(phasor.real if phasor else None),
        _number(phasor.imag if phasor else None),
    )
