"""Versioned, data-only FC22 test lots and deterministic filter evaluation.

No dynamic code execution, device I/O or Qt dependencies. One engine instance is
owned by one FC22 session; input channels are populated by existing adapters.
"""

from __future__ import annotations

import json
import math
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from wolfeye.services.beacheye import settings_point_catalog


@lru_cache(maxsize=8)
def known_points(model: str, build: int | None = None) -> dict[str, frozenset[str]]:
    """Use the company catalog and the same duplicate names as Measurements.

    An offline lot may target either generation; a live editor uses its DUT's
    exact build. Counters have indexed names in the measurement wire format.
    """
    points: dict[str, set[str]] = {"analog": set(), "binary": set()}
    for revision in (build,) if build else (50, 51, 65535):
        catalog = settings_point_catalog(model, revision)
        for channel in points:
            seen: set[str] = set()
            for point_id, name in catalog[channel]:
                key = name if name not in seen else f"{name} [{point_id - 1}]"
                seen.add(name)
                points[channel].add(key)
    return {**{channel: frozenset(names) for channel, names in points.items()},
            "counters": frozenset(f"Counter {index}" for index in range(41))}

ALLOWED_CHANNELS = frozenset({"analog", "binary", "counters", "external", "emwolf"})
EMWOLF_POINT = re.compile(r"scenario_[1-9][0-9]*\.(trip_time_ms|di_input|di_value|operation|completed)\Z")
FILTERS = frozenset({"range", "equals", "tolerance", "stable", "condition", "timeout", "transition", "manual"})
STATUSES = frozenset({"PASS", "FAIL", "NOT_TESTED", "INVALID"})
PROTECTED_FIELDS = frozenset({
    "capacitor_series", "capacitance", "voltage_rating", "temperature",
    "booster_output_voltage", "reclose_4_shot", "dcd", "reset_mode",
    "trip_close_voltage", "aux_igbt_version",
})


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a measurement")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("measurement must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError("measurement must be finite")
    return number


def _source(source: object) -> tuple[str, str]:
    if not isinstance(source, str) or "." not in source:
        raise ValueError("source must be channel.point")
    channel, point = source.split(".", 1)
    if channel not in ALLOWED_CHANNELS or not point.strip():
        raise ValueError(f"unsupported source: {source}")
    if channel == "emwolf" and not EMWOLF_POINT.fullmatch(point):
        raise ValueError(f"unknown emwolf point: {point}")
    return channel, point


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 1000:
        raise ValueError(f"{name} must be an integer between 1 and 1000")
    return value


def validate_lot(data: object, allowed_fields: set[str] | None = None) -> dict[str, Any]:
    """Validate an untrusted JSON lot; return a detached plain-data copy."""
    if not isinstance(data, dict) or data.get("version") != 1 or isinstance(data.get("version"), bool):
        raise ValueError("test lot version must be 1")
    for name in ("lot_id", "device_model"):
        if not isinstance(data.get(name), str) or not data[name].strip():
            raise ValueError(f"{name} is required")
    if data["device_model"] not in ("FC22AR", "FC22S"):
        raise ValueError("device_model must be FC22AR or FC22S")
    catalog = known_points(data["device_model"])

    def check_source(source: object) -> tuple[str, str]:
        channel, point = _source(source)
        if channel in catalog and point not in catalog[channel]:
            if channel != "counters" or not re.fullmatch(r"Counter (0|[1-9][0-9]{0,3})", point) or int(point.split()[1]) > 4094:
                raise ValueError(f"unknown {channel} point: {point}")
        return channel, point
    if "max_age_seconds" in data:
        if not isinstance(data["max_age_seconds"], (int, float)) or isinstance(data["max_age_seconds"], bool) or not 0 < _number(data["max_age_seconds"]) <= 3600:
            raise ValueError("max_age_seconds must be between 0 and 3600")
    tests = data.get("tests")
    if not isinstance(tests, list) or not tests or len(tests) > 256:
        raise ValueError("tests must contain 1 to 256 entries")
    seen_ids: set[str] = set()
    seen_fields: set[str] = set()
    for test in tests:
        if not isinstance(test, dict):
            raise ValueError("each test must be an object")
        test_id, field = test.get("id"), test.get("report_field")
        if not isinstance(test_id, str) or not test_id.strip() or test_id in seen_ids:
            raise ValueError("test IDs must be nonempty and unique")
        seen_ids.add(test_id)
        if not isinstance(field, str) or not field.strip() or field in seen_fields:
            raise ValueError(f"{test_id}: report_field must be nonempty and unique")
        if field in PROTECTED_FIELDS or (allowed_fields is not None and field not in allowed_fields):
            raise ValueError(f"{test_id}: report_field is not eligible for automation: {field}")
        seen_fields.add(field)
        channel, point = check_source(test.get("source"))
        if "unit" in test and not isinstance(test["unit"], str):
            raise ValueError(f"{test_id}: unit must be text")
        if channel == "emwolf" and point.endswith(".trip_time_ms") and test.get("unit") != "ms":
            raise ValueError(f"{test_id}: EmWolf trip time requires unit ms")
        filters = test.get("filters")
        if not isinstance(filters, list) or not filters or len(filters) > 16:
            raise ValueError(f"{test_id}: filters must contain 1 to 16 entries")
        for filt in filters:
            if not isinstance(filt, dict) or filt.get("type") not in FILTERS:
                raise ValueError(f"{test_id}: unsupported filter")
            kind = filt["type"]
            if kind == "range":
                if not all(isinstance(filt.get(k), (int, float)) and not isinstance(filt.get(k), bool) for k in ("min", "max")):
                    raise ValueError(f"{test_id}: range limits must be numeric")
                if _number(filt.get("min")) > _number(filt.get("max")):
                    raise ValueError(f"{test_id}: min exceeds max")
            elif kind == "equals":
                if "value" not in filt or not isinstance(filt["value"], (str, int, float, bool)):
                    raise ValueError(f"{test_id}: equals requires a scalar value")
                if isinstance(filt["value"], float):
                    _number(filt["value"])
            elif kind == "tolerance":
                if not isinstance(test.get("expected"), (int, float)) or isinstance(test.get("expected"), bool):
                    raise ValueError(f"{test_id}: expected must be numeric")
                _number(test.get("expected"))
                if not isinstance(filt.get("limit"), (int, float)) or isinstance(filt.get("limit"), bool):
                    raise ValueError(f"{test_id}: tolerance limit must be numeric")
                if _number(filt.get("limit")) < 0 or filt.get("mode", "absolute") not in ("absolute", "percent"):
                    raise ValueError(f"{test_id}: invalid tolerance")
            elif kind == "stable":
                _positive_int(filt.get("samples"), "samples")
                if not isinstance(filt.get("max_spread"), (int, float)) or isinstance(filt.get("max_spread"), bool):
                    raise ValueError(f"{test_id}: max_spread must be numeric")
                if _number(filt.get("max_spread")) < 0:
                    raise ValueError(f"{test_id}: max_spread must be nonnegative")
            elif kind == "condition":
                check_source(filt.get("source"))
                if "equals" not in filt or not isinstance(filt["equals"], (str, int, float, bool)):
                    raise ValueError(f"{test_id}: condition needs equals")
            elif kind == "timeout":
                if not isinstance(filt.get("seconds"), (int, float)) or isinstance(filt.get("seconds"), bool):
                    raise ValueError(f"{test_id}: timeout seconds must be numeric")
                if _number(filt.get("seconds")) <= 0:
                    raise ValueError(f"{test_id}: timeout seconds must be positive")
            elif kind == "transition":
                if "from" not in filt or "to" not in filt:
                    raise ValueError(f"{test_id}: transition needs from and to")
                if not all(isinstance(filt[k], (str, int, float, bool)) for k in ("from", "to")):
                    raise ValueError(f"{test_id}: transition endpoints must be scalar")
    # JSON round-trip also rejects Python objects/NaN that cannot be stored safely.
    return json.loads(json.dumps(data, allow_nan=False))


def load_lot(path: str | Path, allowed_fields: set[str] | None = None) -> dict[str, Any]:
    return validate_lot(json.loads(Path(path).read_text(encoding="utf-8")), allowed_fields)


def _read(data: Mapping[str, Any], source: str) -> tuple[bool, Any]:
    channel, point = _source(source)
    values = data.get(channel, {})
    if not isinstance(values, Mapping) or point not in values:
        return False, None
    return True, values[point]


def _equal(left: Any, right: Any) -> bool:
    # Boolean/integer confusion is unsafe, but 50 and 50.0 are equivalent.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right


@dataclass(frozen=True)
class Result:
    status: str
    reason: str
    value: Any = None
    source: str = ""
    unit: str = ""
    timestamp: str = ""

    def as_dict(self) -> dict[str, Any]:
        return vars(self).copy()


class TestLotEngine:
    """Applies all filters (AND) to each fresh input and retains sample history."""

    def __init__(self, lot: Mapping[str, Any], allowed_fields: set[str] | None = None) -> None:
        self.lot = validate_lot(dict(lot), allowed_fields)
        self._samples: dict[str, deque[float]] = {}
        self._sample_timestamps: dict[str, str] = {}
        self._transition_started: set[str] = set()
        self._transition_passed: set[str] = set()
        self._first_seen: dict[str, datetime] = {}
        self._timeout_completed: set[str] = set()

    def reset_channel(self, channel: str) -> None:
        """Restart only tests depending on a new procedural run."""
        for test in self.lot["tests"]:
            depends_on_channel = _source(test["source"])[0] == channel or any(
                filt["type"] == "condition" and _source(filt["source"])[0] == channel
                for filt in test["filters"]
            )
            if not depends_on_channel:
                continue
            test_id = test["id"]
            self._first_seen.pop(test_id, None)
            self._timeout_completed.discard(test_id)
            for index, _filt in enumerate(test["filters"]):
                key = f"{test_id}:{index}"
                self._samples.pop(key, None)
                self._sample_timestamps.pop(key, None)
                self._transition_started.discard(key)
                self._transition_passed.discard(key)

    def evaluate(
        self, data: Mapping[str, Any], timestamp: datetime | None = None,
        source_timestamps: Mapping[str, object] | None = None,
        active_channels: set[str] | None = None,
    ) -> dict[str, Result]:
        now = timestamp or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.astimezone()
        iso = now.isoformat(timespec="microseconds")
        results: dict[str, Result] = {}
        for test in self.lot["tests"]:
            test_id, source = test["id"], test["source"]
            if active_channels is not None and _source(source)[0] not in active_channels:
                results[test["report_field"]] = Result(
                    "NOT_TESTED", "input channel is inactive", source=source,
                    unit=test.get("unit", ""), timestamp=iso,
                )
                continue
            self._first_seen.setdefault(test_id, now)
            has_value, value = _read(data, source)
            status, reason = "PASS", "all filters passed"
            if not has_value or value is None:
                status, reason = "NOT_TESTED", "measurement not available"
            elif not isinstance(value, (str, int, float, bool)):
                status, reason = "INVALID", "unsupported measurement type"
            elif isinstance(value, float) and not math.isfinite(value):
                status, reason = "INVALID", "non-finite measurement"
            else:
                for index, filt in enumerate(test["filters"]):
                    kind = filt["type"]
                    try:
                        if kind == "manual":
                            status, reason = "NOT_TESTED", "requires operator confirmation"
                        elif kind == "condition":
                            present, other = _read(data, filt["source"])
                            if not present or not _equal(other, filt["equals"]):
                                status, reason = "NOT_TESTED", "precondition not satisfied"
                        elif kind == "range":
                            reading = _number(value)
                            if not filt["min"] <= reading <= filt["max"]:
                                status, reason = "FAIL", "outside accepted range"
                        elif kind == "equals":
                            if not _equal(value, filt["value"]):
                                status, reason = "FAIL", "unexpected value"
                        elif kind == "tolerance":
                            limit = filt["limit"]
                            if filt.get("mode", "absolute") == "percent":
                                limit = abs(test["expected"]) * limit / 100
                            if abs(_number(value) - test["expected"]) > limit:
                                status, reason = "FAIL", "outside tolerance"
                        elif kind == "stable":
                            key = f"{test_id}:{index}"
                            maximum = filt["samples"]
                            readings = self._samples.setdefault(key, deque(maxlen=maximum))
                            channel = _source(source)[0]
                            sample_stamp = (
                                str(source_timestamps.get(source, source_timestamps.get(channel, iso)))
                                if source_timestamps is not None else iso
                            )
                            if self._sample_timestamps.get(key) != sample_stamp:
                                readings.append(_number(value))
                                self._sample_timestamps[key] = sample_stamp
                            if len(readings) < maximum:
                                status, reason = "NOT_TESTED", "collecting stability samples"
                            elif max(readings) - min(readings) > filt["max_spread"]:
                                status, reason = "FAIL", "unstable measurement"
                        elif kind == "timeout":
                            # Timeout is meaningful for a missing/awaited event; handled below.
                            pass
                        elif kind == "transition":
                            key = f"{test_id}:{index}"
                            if _equal(value, filt["from"]):
                                self._transition_started.add(key)
                            if key in self._transition_started and _equal(value, filt["to"]):
                                self._transition_passed.add(key)
                            if key not in self._transition_passed:
                                status, reason = "NOT_TESTED", "awaiting transition"
                        if status != "PASS":
                            break
                    except (ValueError, TypeError, OverflowError) as exc:
                        status, reason = "INVALID", str(exc)
                        break
            # A failed/invalid/inapplicable reading breaks a consecutive stability run.
            if status in ("FAIL", "INVALID") or (
                status == "NOT_TESTED" and reason != "collecting stability samples"
            ):
                for index, filt in enumerate(test["filters"]):
                    if filt["type"] == "stable":
                        key = f"{test_id}:{index}"
                        self._samples.pop(key, None)
                        self._sample_timestamps.pop(key, None)
            # A late response never becomes PASS. A timely response meets the
            # deadline once; subsequent live-range checks still run normally.
            deadlines = [f["seconds"] for f in test["filters"] if f["type"] == "timeout"]
            if deadlines and test_id not in self._timeout_completed:
                elapsed = (now - self._first_seen[test_id]).total_seconds()
                if elapsed >= min(deadlines):
                    status, reason = "FAIL", "timeout waiting for test result"
                elif status == "PASS":
                    self._timeout_completed.add(test_id)
            results[test["report_field"]] = Result(
                status=status, reason=reason, value=value if has_value else None,
                source=source, unit=test.get("unit", ""), timestamp=iso,
            )
        return results
