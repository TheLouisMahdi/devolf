"""WI03 procedure data and unit-aware acceptance without hardware commands."""
from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from wolfeye.models import MeasurementSnapshot


def instruction_path() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "test_lots" / "wi03.json"


def number(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("A boolean is not a numeric reading")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Enter a numeric reading") from exc
    if not result.is_finite():
        raise ValueError("Reading must be finite")
    return result


def validate_instruction(value: object) -> dict:
    if not isinstance(value, dict) or value.get("format") != "fc22_instruction" or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported instruction JSON format")
    document = value.get("document", {})
    if not document.get("code") or not document.get("revision") or not isinstance(document.get("page_count"), int):
        raise ValueError("Instruction document metadata is required")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > 256:
        raise ValueError("Instruction must contain 1–256 test cases")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not case.get("id") or case["id"] in ids:
            raise ValueError("Case IDs must be unique")
        ids.add(case["id"])
        if not case.get("models") or any(model not in ("FC22AR", "FC22S") for model in case["models"]):
            raise ValueError("Each case requires valid DUT models")
        if not case.get("pages") or any(type(page) is not int or not 1 <= page <= document["page_count"] for page in case["pages"]):
            raise ValueError("Each case requires valid source pages")
        if not all(isinstance(case.get(key), str) and case[key] for key in ("board", "title", "setup")):
            raise ValueError("Board, title and setup are required")
        if not isinstance(case.get("checks"), list) or not case["checks"]:
            raise ValueError("Case has no acceptance checks")
        checks = set()
        for row in case["checks"] + case.get("inputs", []):
            if not isinstance(row, dict) or not row.get("id") or not row.get("unit") or not row.get("source_expression"):
                raise ValueError("Every parameter needs an ID, unit and source expression")
            if row in case["checks"]:
                if row["id"] in checks:
                    raise ValueError("Check IDs must be unique within each case")
                checks.add(row["id"])
            rule = row.get("acceptance", {})
            kind = rule.get("type")
            if kind == "tolerance":
                number(rule.get("nominal"))
                if number(rule.get("absolute")) < 0:
                    raise ValueError("Tolerance cannot be negative")
            elif kind == "range":
                if "min" not in rule and "max" not in rule:
                    raise ValueError("Range requires a boundary")
                for boundary in ("min", "max"):
                    if boundary in rule:
                        number(rule[boundary])
                    if boundary + "_inclusive" in rule and type(rule[boundary + "_inclusive"]) is not bool:
                        raise ValueError("Boundary inclusivity must be boolean")
                if "min" in rule and "max" in rule and number(rule["min"]) > number(rule["max"]):
                    raise ValueError("Range boundaries are reversed")
            elif kind == "equals":
                if type(rule.get("value")) is not bool or row["unit"] != "boolean":
                    raise ValueError("Qualitative checks require a boolean observation")
            elif kind == "boundary_tolerances":
                for boundary in ("lower", "upper"):
                    number(rule[boundary]["nominal"])
                    if number(rule[boundary]["absolute"]) < 0:
                        raise ValueError("Boundary tolerance cannot be negative")
                if not row.get("requires_review"):
                    raise ValueError("Toleranced boundaries need an explicit review marker")
            elif kind != "unspecified":
                raise ValueError("Unknown acceptance rule")
            binding = row.get("binding")
            if binding:
                if binding.get("unit") != row["unit"] or not isinstance(binding.get("source"), str) or not binding["source"].startswith(("analog.", "binary.")):
                    raise ValueError("Binding must declare its measurement source and matching unit")
                if number(binding.get("multiplier")) <= 0:
                    raise ValueError("Binding multiplier must be positive")
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def load_instruction(path: str | Path | None = None) -> dict:
    return validate_instruction(json.loads(Path(path or instruction_path()).read_text(encoding="utf-8")))


def native_readings(case: dict, snapshot: MeasurementSnapshot) -> dict:
    readings = {}
    for row in case["checks"]:
        binding = row.get("binding")
        if not binding:
            continue
        channel, point = binding["source"].split(".", 1)
        value = getattr(snapshot, channel).get(point)
        if value is None:
            continue
        try:
            if row["unit"] == "boolean":
                if type(value) is not bool:
                    continue
                converted = value
            else:
                converted = float(number(value) * number(binding["multiplier"]))
            readings[row["id"]] = {"value": converted, "unit": row["unit"], "source": binding["source"],
                                    "input_kind": "device", "raw_value": value,
                                    "timestamp": snapshot.timestamp.isoformat()}
        except ValueError:
            continue
    return readings


def evaluate_case(case: dict, readings: dict, *, setup_confirmed: bool, model: str) -> dict:
    results = {}
    for row in case["checks"]:
        reading = readings.get(row["id"], {})
        value = reading.get("value")
        result = {**reading, "status": "NOT_TESTED", "reason": "Measurement not available", "unit": row["unit"]}
        rule = row["acceptance"]
        if model not in case["models"]:
            result["reason"] = "Test case does not match the DUT model"
        elif not setup_confirmed:
            result["reason"] = "Confirm the specified input and test setup first"
        elif row.get("requires_review") or rule["type"] in ("boundary_tolerances", "unspecified"):
            result["reason"] = row.get("requires_review", "WI03 provides no numerical acceptance limit")
        elif value is not None:
            try:
                if reading.get("unit") != row["unit"]:
                    raise ValueError("Measurement unit does not match WI03")
                if rule["type"] == "equals":
                    if type(value) is not bool:
                        raise ValueError("Enter an explicit true/false observation")
                    passed = value == rule["value"]
                else:
                    measured = number(value)
                    if rule["type"] == "tolerance":
                        nominal, absolute = number(rule["nominal"]), number(rule["absolute"])
                        passed = nominal - absolute <= measured <= nominal + absolute
                    else:
                        passed = True
                        if "min" in rule:
                            low = number(rule["min"])
                            passed = passed and (measured >= low if rule.get("min_inclusive", True) else measured > low)
                        if "max" in rule:
                            high = number(rule["max"])
                            passed = passed and (measured <= high if rule.get("max_inclusive", True) else measured < high)
                result.update(status="PASS" if passed else "FAIL", reason="WI03 criterion met" if passed else "Outside WI03 acceptance condition")
            except ValueError as exc:
                result.update(status="INVALID", reason=str(exc))
        results[row["id"]] = result
    return results
