from __future__ import annotations

import cmath
import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any


from itertools import zip_longest


def _strict_zip(left, right):
    """Keep equal-length validation on Python 3.8 as well as newer runtimes."""
    missing = object()
    for a, b in zip_longest(left, right, fillvalue=missing):
        if a is missing or b is missing:
            raise ValueError("zip arguments have different lengths")
        yield a, b

class SignalAnalysisError(ValueError):
    pass


@dataclass(frozen=True)
class Phasor:
    value: complex

    @property
    def magnitude(self) -> float:
        return abs(self.value)

    @property
    def angle_deg(self) -> float:
        return _normalize_angle(math.degrees(cmath.phase(self.value)))

    @property
    def real(self) -> float:
        return self.value.real

    @property
    def imag(self) -> float:
        return self.value.imag


@dataclass(frozen=True)
class Harmonic:
    order: int
    frequency_hz: float
    phasor: Phasor | None
    percent_of_fundamental: float | None

    @property
    def available(self) -> bool:
        return self.phasor is not None


@dataclass(frozen=True)
class ChannelAnalysis:
    name: str
    unit: str
    dc_offset: float
    true_rms: float
    fundamental: Phasor | None
    harmonics: dict[int, Harmonic] = field(default_factory=dict)
    thd_percent: float | None = None
    spectrum: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class DirectionalAnalysis:
    polarising: str
    operating: str
    angle_deg: float | None
    torque_angle_deg: float | None
    state: str = "Not Configured"
    in_cos_theta: float | None = None
    in_sin_theta: float | None = None


@dataclass(frozen=True)
class ProtectionAnalysis:
    quantity: float | None
    pickup: float | None
    multiple: float | None
    state: str
    unit: str = "A"


@dataclass(frozen=True)
class SignalAnalysisResult:
    sample_rate_hz: float | None
    sample_count: int
    power_quality_sample_count: int
    phase_sequence: str
    channels: dict[str, ChannelAnalysis]
    angle_differences: dict[str, float]
    sequences: dict[str, Phasor]
    residual_current: Phasor | None
    residual_voltage: Phasor | None
    measured_in_difference: float | None
    i2_i1_percent: float | None
    voltage_thd_percent: float | None
    current_thd_percent: float | None
    current_tdd_percent: float | None
    directional: dict[str, DirectionalAnalysis]
    protection: dict[str, ProtectionAnalysis]


@dataclass(frozen=True)
class MovingSignalAnalysis:
    start_sample: int
    end_sample: int
    result: SignalAnalysisResult


class SignalAnalyzer:
    def __init__(self, remove_dc_for_rms: bool = False) -> None:
        self.remove_dc_for_rms = remove_dc_for_rms

    def analyze(
        self,
        samples: dict[str, Sequence[float]],
        sample_rate_hz: float | None,
        rated_frequency_hz: float | None,
        config: dict[str, Any] | None = None,
        power_quality_samples: dict[str, Sequence[float]] | None = None,
    ) -> SignalAnalysisResult:
        prepared = self._validate(samples)
        sample_count = len(next(iter(prepared.values())))
        sample_rate = self._valid_positive(sample_rate_hz)
        analysis_frequency = self._valid_positive(rated_frequency_hz)

        channels = {
            name: self._analyze_channel(
                name, values, sample_rate, analysis_frequency, False
            )
            for name, values in prepared.items()
        }
        power_quality_sample_count = 0
        if power_quality_samples:
            quality_prepared = self._validate(power_quality_samples)
            power_quality_sample_count = len(next(iter(quality_prepared.values())))
            quality_channels = {
                name: self._analyze_channel(
                    name, values, sample_rate, analysis_frequency, True
                )
                for name, values in quality_prepared.items()
            }
            channels = {
                name: replace(
                    channel,
                    harmonics=quality_channels[name].harmonics,
                    thd_percent=quality_channels[name].thd_percent,
                    spectrum=quality_channels[name].spectrum,
                )
                if name in quality_channels
                else channel
                for name, channel in channels.items()
            }
        sequences = self._sequence_components(channels)
        residual_current = self._sum_phasors(channels, ("Ia", "Ib", "Ic"))
        residual_voltage = self._sum_phasors(channels, ("Va", "Vb", "Vc"))
        measured_in = self._fundamental(channels, "In")
        measured_in_difference = (
            abs(measured_in.value - residual_current.value)
            if measured_in is not None and residual_current is not None
            else None
        )
        i1 = sequences.get("I1")
        i2 = sequences.get("I2")
        i2_i1 = (
            (i2.magnitude / i1.magnitude) * 100
            if i1 is not None and i2 is not None and i1.magnitude > 1e-12
            else None
        )
        voltage_thd = self._max_available(
            channels.get(name).thd_percent if name in channels else None
            for name in ("Va", "Vb", "Vc")
        )
        current_thd = self._max_available(
            channels.get(name).thd_percent if name in channels else None
            for name in ("Ia", "Ib", "Ic", "In")
        )
        current_tdd = None
        directional = self._directional(channels, sequences, config)
        protection = self._protection(
            channels,
            sequences,
            residual_current,
            voltage_thd,
            current_tdd,
            config,
        )
        phase_sequence = self._phase_sequence(sequences)
        angle_differences = self._angle_differences(channels)

        return SignalAnalysisResult(
            sample_rate_hz=sample_rate,
            sample_count=sample_count,
            power_quality_sample_count=power_quality_sample_count,
            phase_sequence=phase_sequence,
            channels=channels,
            angle_differences=angle_differences,
            sequences=sequences,
            residual_current=residual_current,
            residual_voltage=residual_voltage,
            measured_in_difference=measured_in_difference,
            i2_i1_percent=i2_i1,
            voltage_thd_percent=voltage_thd,
            current_thd_percent=current_thd,
            current_tdd_percent=current_tdd,
            directional=directional,
            protection=protection,
        )

    def analyze_moving(
        self,
        samples: dict[str, Sequence[float]],
        sample_rate_hz: float | None,
        rated_frequency_hz: float | None,
        config: dict[str, Any] | None = None,
        window_size: int = 64,
        step_size: int = 64,
    ) -> tuple[MovingSignalAnalysis, ...]:
        if window_size < 4:
            raise SignalAnalysisError("Analysis window must contain at least 4 samples")
        if step_size < 1:
            raise SignalAnalysisError("Analysis step must be at least 1 sample")
        prepared = self._validate(samples)
        sample_count = len(next(iter(prepared.values())))
        if sample_count < window_size:
            raise SignalAnalysisError(
                f"Signal capture needs at least {window_size} samples for moving analysis"
            )
        sample_rate = self._valid_positive(sample_rate_hz)
        quality_window_size = round(sample_rate * 0.2) if sample_rate else None
        windows = []
        for start in range(0, sample_count - window_size + 1, step_size):
            end = start + window_size
            quality_samples = (
                {
                    name: values[end - quality_window_size : end]
                    for name, values in prepared.items()
                }
                if quality_window_size and end >= quality_window_size
                else None
            )
            windows.append(
                MovingSignalAnalysis(
                    start,
                    end,
                    self.analyze(
                        {
                            name: values[start:end]
                            for name, values in prepared.items()
                        },
                        sample_rate_hz,
                        rated_frequency_hz,
                        config,
                        quality_samples,
                    ),
                )
            )
        return tuple(windows)

    def _validate(
        self, samples: dict[str, Sequence[float]]
    ) -> dict[str, tuple[float, ...]]:
        prepared: dict[str, tuple[float, ...]] = {}
        for name, source in samples.items():
            if not source:
                continue
            values = tuple(float(value) for value in source)
            if not all(math.isfinite(value) for value in values):
                raise SignalAnalysisError(f"{name} contains a non-finite sample")
            prepared[name] = values
        if not prepared:
            raise SignalAnalysisError("No signal samples are available")
        lengths = {len(values) for values in prepared.values()}
        if len(lengths) != 1:
            raise SignalAnalysisError("Signal channels must have equal sample counts")
        if next(iter(lengths)) < 4:
            raise SignalAnalysisError("Signal capture is too short")
        return prepared

    def _analyze_channel(
        self,
        name: str,
        values: tuple[float, ...],
        sample_rate_hz: float | None,
        frequency_hz: float | None,
        calculate_power_quality: bool,
    ) -> ChannelAnalysis:
        dc_offset = sum(values) / len(values)
        rms_values = (
            tuple(value - dc_offset for value in values)
            if self.remove_dc_for_rms
            else values
        )
        true_rms = math.sqrt(sum(value * value for value in rms_values) / len(values))
        unit = "A" if name.startswith("I") else "V"
        fundamental = None
        harmonics: dict[int, Harmonic] = {}
        spectrum: tuple[tuple[float, float], ...] = ()
        thd = None

        if sample_rate_hz and frequency_hz:
            fundamental = _fit_phasor(values, sample_rate_hz, frequency_hz)
        if sample_rate_hz and frequency_hz and calculate_power_quality:
            nyquist = sample_rate_hz / 2
            for order in range(1, 16):
                harmonic_frequency = frequency_hz * order
                phasor = (
                    _fit_phasor(values, sample_rate_hz, harmonic_frequency)
                    if harmonic_frequency <= nyquist
                    else None
                )
                percent = (
                    (phasor.magnitude / fundamental.magnitude) * 100
                    if phasor is not None
                    and fundamental is not None
                    and fundamental.magnitude > 1e-12
                    else None
                )
                harmonics[order] = Harmonic(order, harmonic_frequency, phasor, percent)
            thd = self._thd(harmonics)
            spectrum = _spectrum(values, sample_rate_hz)

        return ChannelAnalysis(
            name=name,
            unit=unit,
            dc_offset=dc_offset,
            true_rms=true_rms,
            fundamental=fundamental,
            harmonics=harmonics,
            thd_percent=thd,
            spectrum=spectrum,
        )

    @staticmethod
    def _sequence_components(
        channels: dict[str, ChannelAnalysis],
    ) -> dict[str, Phasor]:
        result: dict[str, Phasor] = {}
        rotation = cmath.exp(2j * math.pi / 3)
        for prefix in ("V", "I"):
            phase_names = (f"{prefix}a", f"{prefix}b", f"{prefix}c")
            values = [
                channels[name].fundamental.value
                for name in phase_names
                if name in channels and channels[name].fundamental is not None
            ]
            if len(values) != 3:
                continue
            phase_a, phase_b, phase_c = values
            result[f"{prefix}0"] = Phasor((phase_a + phase_b + phase_c) / 3)
            result[f"{prefix}1"] = Phasor(
                (phase_a + rotation * phase_b + rotation**2 * phase_c) / 3
            )
            result[f"{prefix}2"] = Phasor(
                (phase_a + rotation**2 * phase_b + rotation * phase_c) / 3
            )
        return result

    @staticmethod
    def _sum_phasors(
        channels: dict[str, ChannelAnalysis], names: tuple[str, ...]
    ) -> Phasor | None:
        phasors = [
            channels[name].fundamental
            for name in names
            if name in channels and channels[name].fundamental is not None
        ]
        return (
            Phasor(sum((item.value for item in phasors), 0j))
            if len(phasors) == 3
            else None
        )

    @staticmethod
    def _fundamental(channels: dict[str, ChannelAnalysis], name: str) -> Phasor | None:
        channel = channels.get(name)
        return channel.fundamental if channel else None

    @staticmethod
    def _phase_sequence(sequences: dict[str, Phasor]) -> str:
        positive = sequences.get("V1")
        negative = sequences.get("V2")
        if positive is None or negative is None:
            return "Unknown"
        reference = max(positive.magnitude, negative.magnitude)
        if reference <= 1e-9:
            return "Unknown"
        if positive.magnitude > negative.magnitude * 1.2:
            return "ABC"
        if negative.magnitude > positive.magnitude * 1.2:
            return "ACB"
        return "Unknown"

    @staticmethod
    def _angle_differences(
        channels: dict[str, ChannelAnalysis],
    ) -> dict[str, float]:
        pairs = (
            ("Va-Vb", "Va", "Vb"),
            ("Vb-Vc", "Vb", "Vc"),
            ("Vc-Va", "Vc", "Va"),
            ("Va-Ia", "Va", "Ia"),
            ("Vb-Ib", "Vb", "Ib"),
            ("Vc-Ic", "Vc", "Ic"),
        )
        result: dict[str, float] = {}
        for label, left, right in pairs:
            left_phasor = SignalAnalyzer._fundamental(channels, left)
            right_phasor = SignalAnalyzer._fundamental(channels, right)
            if left_phasor is not None and right_phasor is not None:
                result[label] = _normalize_angle(
                    left_phasor.angle_deg - right_phasor.angle_deg
                )
        return result

    @staticmethod
    def _thd(harmonics: dict[int, Harmonic]) -> float | None:
        fundamental = harmonics.get(1)
        if fundamental is None or fundamental.phasor is None:
            return None
        magnitude = fundamental.phasor.magnitude
        if magnitude <= 1e-12:
            return None
        available = [
            harmonic.phasor.magnitude
            for order, harmonic in harmonics.items()
            if order >= 2 and harmonic.phasor is not None
        ]
        return math.sqrt(sum(value * value for value in available)) / magnitude * 100

    @staticmethod
    def _max_available(values) -> float | None:
        available = [value for value in values if value is not None]
        return max(available) if available else None

    @staticmethod
    def _directional(
        channels: dict[str, ChannelAnalysis],
        sequences: dict[str, Phasor],
        config: dict[str, Any] | None,
    ) -> dict[str, DirectionalAnalysis]:
        measured_in = SignalAnalyzer._fundamental(channels, "In")
        pairs = {
            "OC": ("V1", "I1", sequences.get("V1"), sequences.get("I1")),
            "NPS": ("V2", "I2", sequences.get("V2"), sequences.get("I2")),
            "EF": ("V0", "I0", sequences.get("V0"), sequences.get("I0")),
            "SEF": (
                "V0",
                "In" if measured_in else "I0",
                sequences.get("V0"),
                measured_in or sequences.get("I0"),
            ),
        }
        group = _active_protection_group(config)
        master = group.get("master", {}).get("directional", {}) if group else {}
        results: dict[str, DirectionalAnalysis] = {}
        for name, (voltage_name, current_name, voltage, current) in pairs.items():
            angle = (
                _normalize_angle(voltage.angle_deg - current.angle_deg)
                if voltage is not None
                and current is not None
                and voltage.magnitude > 1e-12
                and current.magnitude > 1e-12
                else None
            )
            element = group.get(name.lower(), {}) if group else {}
            torque = _valid_number(element.get("torque_angle_deg"))
            settings = master.get(name.lower(), {})
            configured = any(bool(stage) for stage in settings.get("stages", []))
            if not configured:
                state = "Not Configured"
            elif angle is None or torque is None:
                state = "Not Detected"
            else:
                offset = abs(_normalize_angle(angle - torque))
                state = "Forward" if offset <= 90 else "Reverse"
            projection_cos = (
                current.magnitude * math.cos(math.radians(angle))
                if name == "SEF" and current is not None and angle is not None
                else None
            )
            projection_sin = (
                current.magnitude * math.sin(math.radians(angle))
                if name == "SEF" and current is not None and angle is not None
                else None
            )
            results[name] = DirectionalAnalysis(
                voltage_name,
                current_name,
                angle,
                torque,
                state,
                in_cos_theta=projection_cos,
                in_sin_theta=projection_sin,
            )
        return results

    @staticmethod
    def _protection(
        channels: dict[str, ChannelAnalysis],
        sequences: dict[str, Phasor],
        residual_current: Phasor | None,
        voltage_thd: float | None,
        current_tdd: float | None,
        config: dict[str, Any] | None,
    ) -> dict[str, ProtectionAnalysis]:
        phase_currents = [
            channels[name].fundamental.magnitude
            for name in ("Ia", "Ib", "Ic")
            if name in channels and channels[name].fundamental is not None
        ]
        measured_in = SignalAnalyzer._fundamental(channels, "In")
        quantities = {
            "OC": max(phase_currents) if phase_currents else None,
            "EF": measured_in.magnitude
            if measured_in
            else _magnitude(residual_current),
            "SEF": measured_in.magnitude
            if measured_in
            else _magnitude(residual_current),
            "NPS": _magnitude(sequences.get("I2")),
        }
        group = _active_protection_group(config)
        protection = config.get("protection", {}) if config else {}
        enabled_flags = {
            "OC": bool(protection.get("enabled") and protection.get("oc_enabled")),
            "EF": bool(protection.get("enabled") and protection.get("ef_enabled")),
            "SEF": bool(protection.get("enabled") and protection.get("sef_enabled")),
            "NPS": bool(
                protection.get("enabled")
                and protection.get("feature_flags", {}).get("nps")
            ),
        }
        results: dict[str, ProtectionAnalysis] = {}
        for name, quantity in quantities.items():
            elements = group.get(name.lower(), {}).get("elements", []) if group else []
            active = [item for item in elements if item.get("enabled")]
            pickup_values = [
                value
                for item in active
                if (value := _valid_number(item.get("pickup_a"))) is not None
                and value > 0
            ]
            pickup = (
                min(pickup_values) if enabled_flags[name] and pickup_values else None
            )
            multiple = quantity / pickup if quantity is not None and pickup else None
            state = (
                "PICKUP"
                if multiple is not None and multiple >= 1
                else "NORMAL"
                if multiple is not None
                else "Not Configured"
            )
            results[name] = ProtectionAnalysis(quantity, pickup, multiple, state)

        master = group.get("master", {}) if group else {}
        feature_flags = protection.get("feature_flags", {})
        broken = master.get("broken_conductor", {})
        broken_enabled = bool(
            protection.get("enabled")
            and feature_flags.get("nps")
            and _mode_enabled(broken.get("mode"))
        )
        broken_pickup = _valid_number(broken.get("pickup_pct"))
        broken_minimum = _valid_number(broken.get("negative_sequence_min_a"))
        phase_maximum = max(phase_currents) if phase_currents else None
        negative_sequence = _magnitude(sequences.get("I2"))
        broken_multiple = (
            i2_i1 / broken_pickup
            if (i2_i1 := _sequence_ratio_percent(sequences)) is not None
            and broken_pickup
            and broken_pickup > 0
            else None
        )
        broken_ready = bool(
            broken_enabled
            and phase_maximum is not None
            and phase_maximum > 3
            and negative_sequence is not None
            and broken_minimum is not None
            and negative_sequence >= broken_minimum
        )
        broken_state = (
            "PICKUP"
            if broken_ready and broken_multiple is not None and broken_multiple >= 1
            else "NORMAL"
            if broken_enabled and broken_multiple is not None
            else "Not Configured"
        )
        results["46BC"] = ProtectionAnalysis(
            i2_i1,
            broken_pickup if broken_enabled else None,
            broken_multiple if broken_enabled else None,
            broken_state,
            "%",
        )

        harmonic = master.get("harmonic", {})
        thd = harmonic.get("thd", {})
        thd_enabled = bool(
            protection.get("enabled")
            and feature_flags.get("harmonic")
            and _mode_enabled(thd.get("mode"))
        )
        thd_pickup = _valid_number(thd.get("level_pct")) if thd_enabled else None
        thd_multiple = (
            voltage_thd / thd_pickup
            if voltage_thd is not None and thd_pickup and thd_pickup > 0
            else None
        )
        thd_state = (
            "PICKUP"
            if thd_multiple is not None and thd_multiple >= 1
            else "NORMAL"
            if thd_multiple is not None
            else "Not Configured"
        )
        results["Voltage THD"] = ProtectionAnalysis(
            voltage_thd,
            thd_pickup,
            thd_multiple,
            thd_state,
            "%",
        )

        tdd = harmonic.get("tdd", {})
        tdd_enabled = bool(
            protection.get("enabled")
            and feature_flags.get("harmonic")
            and _mode_enabled(tdd.get("mode"))
        )
        tdd_pickup = _valid_number(tdd.get("level_pct")) if tdd_enabled else None
        results["Current TDD"] = ProtectionAnalysis(
            current_tdd,
            tdd_pickup,
            None,
            "N/A" if tdd_enabled else "Not Configured",
            "%",
        )
        return results

    @staticmethod
    def _valid_positive(value: float | None) -> float | None:
        parsed = _valid_number(value)
        return parsed if parsed is not None and parsed > 0 else None


def _fit_phasor(
    values: Sequence[float], sample_rate_hz: float, frequency_hz: float
) -> Phasor | None:
    if frequency_hz <= 0 or frequency_hz > sample_rate_hz / 2:
        return None
    rows = [
        (
            math.cos(2 * math.pi * frequency_hz * index / sample_rate_hz),
            math.sin(2 * math.pi * frequency_hz * index / sample_rate_hz),
            1.0,
        )
        for index in range(len(values))
    ]
    matrix = [
        [sum(row[i] * row[j] for row in rows) for j in range(3)] for i in range(3)
    ]
    vector = [
        sum(row[index] * value for row, value in _strict_zip(rows, values))
        for index in range(3)
    ]
    solved = _solve(matrix, vector)
    if solved is None:
        return None
    cosine, sine, _offset = solved
    return Phasor(complex(cosine, -sine) / math.sqrt(2))


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    augmented = [row[:] + [value] for row, value in _strict_zip(matrix, vector)]
    size = len(augmented)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * base
                for value, base in _strict_zip(augmented[row], augmented[column])
            ]
    return [augmented[index][-1] for index in range(size)]


def _spectrum(
    values: Sequence[float], sample_rate_hz: float
) -> tuple[tuple[float, float], ...]:
    centered = [value - (sum(values) / len(values)) for value in values]
    transformed = _fft(centered)
    scale = math.sqrt(2) / len(values)
    return tuple(
        (index * sample_rate_hz / len(values), abs(value) * scale)
        for index, value in enumerate(transformed[: len(values) // 2 + 1])
    )


def _fft(values: Sequence[float]) -> list[complex]:
    size = len(values)
    if size == 1:
        return [complex(values[0])]
    if size % 2:
        return [
            sum(
                value * cmath.exp(-2j * math.pi * output * index / size)
                for index, value in enumerate(values)
            )
            for output in range(size)
        ]
    even = _fft(values[::2])
    odd = _fft(values[1::2])
    factors = [
        cmath.exp(-2j * math.pi * index / size) * odd[index]
        for index in range(size // 2)
    ]
    return [even[index] + factors[index] for index in range(size // 2)] + [
        even[index] - factors[index] for index in range(size // 2)
    ]


def _active_protection_group(
    config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not config:
        return None
    protection = config.get("protection", {})
    groups = protection.get("groups", [])
    try:
        index = int(protection.get("active_group", 1)) - 1
    except (TypeError, ValueError):
        return None
    return groups[index] if 0 <= index < len(groups) else None


def _normalize_angle(value: float) -> float:
    normalized = (value + 180) % 360 - 180
    return 180.0 if normalized == -180 else normalized


def _valid_number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _mode_enabled(value: object) -> bool:
    return str(value).strip().upper() not in {"", "DISABLE", "DISABLED", "NONE"}


def _sequence_ratio_percent(sequences: dict[str, Phasor]) -> float | None:
    positive = sequences.get("I1")
    negative = sequences.get("I2")
    if positive is None or negative is None or positive.magnitude <= 1e-12:
        return None
    return negative.magnitude / positive.magnitude * 100


def _magnitude(value: Phasor | None) -> float | None:
    return value.magnitude if value is not None else None
