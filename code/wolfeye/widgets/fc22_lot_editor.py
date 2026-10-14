"""Native, form-based editor for FC22 JSON test lots.

The editor only changes test definitions. Validation and evaluation remain in
wolfeye.services.fc22_test_lot; no protocol or session logic lives here.
"""

from __future__ import annotations

import copy
import json
import math

from wolfeye.qt import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout,
    QWidget, Qt, Signal,
)
from wolfeye.services.fc22_test_lot import FILTERS, known_points, PROTECTED_FIELDS, validate_lot


FILTER_FIELDS = {
    "range": (("min", "Minimum", "number"), ("max", "Maximum", "number")),
    "equals": (("value", "Expected value", "scalar"),),
    "tolerance": (("limit", "Tolerance", "number"), ("mode", "Mode", "mode")),
    "stable": (("samples", "Samples", "integer"), ("max_spread", "Max spread", "number")),
    "condition": (("source", "Condition source", "source"), ("equals", "Equals", "scalar")),
    "transition": (("from", "From", "scalar"), ("to", "To", "scalar")),
    "timeout": (("seconds", "Time limit (s)", "number"),),
    "manual": (),
}

FILTER_DEFAULTS = {
    "range": {"min": 0, "max": 0},
    "equals": {"value": True},
    "tolerance": {"limit": 0, "mode": "absolute"},
    "stable": {"samples": 5, "max_spread": 0},
    "condition": {"source": "binary.AC supply", "equals": True},
    "transition": {"from": False, "to": True},
    "timeout": {"seconds": 5},
    "manual": {},
}


def _fill_sources(combo: QComboBox, model: str, build: int | None = None) -> None:
    value = combo.currentText()
    blocked = combo.blockSignals(True)
    combo.clear()
    for channel, names in known_points(model, build).items():
        combo.addItems([f"{channel}.{point}" for point in sorted(names)])
    combo.addItems(["external.charging_voltage", "emwolf.scenario_1.trip_time_ms"])
    combo.setEditText(value)
    combo.blockSignals(blocked)


def _source_combo(value: str, model: str = "FC22AR", build: int | None = None) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    _fill_sources(combo, model, build)
    combo.setEditText(value)
    return combo


def _number(text: str, label: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"{label}: enter a number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label}: value must be finite")
    return value


def _scalar(text: str, label: str):
    if not text.strip():
        raise ValueError(f"{label}: enter a value (e.g. true, 50, or \"text\")")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = text
    if type(value) not in (str, int, float, bool):
        raise ValueError(f"{label}: only text, numbers or booleans are supported")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label}: value must be finite")
    return value


class _FilterRow(QGroupBox):
    remove_requested = Signal(object)

    def __init__(self, data: dict, index: int, model: str, build: int | None) -> None:
        super().__init__(f"Filter {index + 1}")
        self._original = copy.deepcopy(data)
        self.model, self.build = model, build
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(sorted(FILTERS))
        self.kind.setCurrentText(data["type"])
        remove = QPushButton("Remove")
        remove.setObjectName("danger")
        remove.clicked.connect(lambda: self.remove_requested.emit(self))
        top.addWidget(QLabel("Type"))
        top.addWidget(self.kind, 1)
        top.addWidget(remove)
        outer.addLayout(top)
        self.params_form = QFormLayout()
        outer.addLayout(self.params_form)
        self.params: dict[str, tuple[QWidget, str]] = {}
        self.kind.currentTextChanged.connect(self._change_kind)
        self._render_params(data)

    def _change_kind(self, kind: str) -> None:
        self._render_params({"type": kind, **FILTER_DEFAULTS[kind]})

    def _render_params(self, data: dict) -> None:
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self.params.clear()
        for name, label, data_type in FILTER_FIELDS[self.kind.currentText()]:
            value = data.get(name, FILTER_DEFAULTS[self.kind.currentText()].get(name, ""))
            if data_type == "source":
                widget = _source_combo(str(value), self.model, self.build)
            elif data_type == "mode":
                widget = QComboBox()
                widget.addItems(("absolute", "percent"))
                widget.setCurrentText(str(value))
            else:
                widget = QLineEdit()
                widget.setText(json.dumps(value) if data_type == "scalar" else str(value))
                if data_type == "scalar":
                    widget.setPlaceholderText('true / false / 50 / "text"')
            self.params_form.addRow(label, widget)
            self.params[name] = (widget, data_type)
        if not self.params:
            hint = QLabel("Operator confirmation required. This filter never auto-passes.")
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            self.params_form.addRow(hint)

    def value(self) -> dict:
        kind = self.kind.currentText()
        result = {"type": kind}
        for name, (widget, data_type) in self.params.items():
            raw = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
            label = f"{kind}.{name}"
            if data_type == "number":
                result[name] = _number(raw, label)
            elif data_type == "integer":
                if not raw.strip().isdigit():
                    raise ValueError(f"{label}: enter a positive whole number")
                result[name] = int(raw)
            elif data_type == "scalar":
                result[name] = _scalar(raw, label)
            else:
                result[name] = raw.strip()
        # Keep extension metadata on an unchanged filter, if present.
        if kind == self._original["type"]:
            return {**self._original, **result}
        return result


class TestLotEditorDialog(QDialog):
    """Graphical editor, returning a validated lot only after explicit Save."""

    def __init__(self, lot: dict | None, model: str, fields: list[tuple[str, str]], parent=None, build: int | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FC22 | Test Lot Configuration")
        self.resize(1060, 730)
        self._fields = [(key, label) for key, label in fields if key not in PROTECTED_FIELDS]
        self._allowed = {key for key, _label in self._fields}
        self._draft = copy.deepcopy(lot) if lot else self._blank_lot(model)
        self.lot: dict | None = None
        self._selected_index: int | None = None
        self._filter_rows: list[_FilterRow] = []
        self._build = build
        self._build_ui()
        self.model.currentTextChanged.connect(self._model_changed)
        self._refresh_tests(0)

    def _blank_lot(self, model: str) -> dict:
        if not self._fields:
            raise ValueError("No eligible report fields")
        return {"version": 1, "lot_id": f"{model}-CUSTOM", "device_model": model,
                "max_age_seconds": 30, "tests": [self._new_test([], 1)]}

    def _new_test(self, tests: list[dict], number: int) -> dict:
        used = {test["report_field"] for test in tests}
        available = next((key for key, _ in self._fields if key not in used), None)
        if available is None:
            raise ValueError("All eligible report fields already have tests")
        names = {test["id"] for test in tests}
        while f"new_test_{number}" in names:
            number += 1
        # The safe initial rule requires operator configuration; never auto-PASS.
        return {"id": f"new_test_{number}", "source": "analog.F ABC",
                "report_field": available, "filters": [{"type": "manual"}]}

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        caption = QLabel("Configure tests and acceptance filters for FC22 data. Changes apply only when Save is pressed.")
        caption.setObjectName("muted")
        root.addWidget(caption)

        profile = QGroupBox("Test Lot")
        profile_grid = QGridLayout(profile)
        self.lot_id = QLineEdit(self._draft["lot_id"])
        self.model = QComboBox()
        self.model.addItems(("FC22AR", "FC22S"))
        self.model.setCurrentText(self._draft["device_model"])
        self.max_age = QLineEdit(str(self._draft.get("max_age_seconds", 30)))
        profile_grid.addWidget(QLabel("Lot ID"), 0, 0)
        profile_grid.addWidget(self.lot_id, 0, 1)
        profile_grid.addWidget(QLabel("Device model"), 0, 2)
        profile_grid.addWidget(self.model, 0, 3)
        profile_grid.addWidget(QLabel("Max data age (s)"), 0, 4)
        profile_grid.addWidget(self.max_age, 0, 5)
        root.addWidget(profile)

        body = QHBoxLayout()
        sidebar = QGroupBox("Tests")
        sidebar.setMinimumWidth(225)
        sidebar.setMaximumWidth(275)
        side = QVBoxLayout(sidebar)
        self.tests_list = QListWidget()
        self.tests_list.currentRowChanged.connect(self._selected_test_changed)
        side.addWidget(self.tests_list, 1)
        buttons = QHBoxLayout()
        add = QPushButton("+ Add test")
        add.clicked.connect(self._add_test)
        remove = QPushButton("Remove")
        remove.setObjectName("danger")
        remove.clicked.connect(self._remove_test)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        side.addLayout(buttons)
        body.addWidget(sidebar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_body = QWidget()
        edit = QVBoxLayout(scroll_body)
        details = QGroupBox("Selected test")
        form = QFormLayout(details)
        self.test_id = QLineEdit()
        self.test_source = _source_combo("analog.F ABC", self.model.currentText(), self._build)
        self.test_field = QComboBox()
        for key, label in self._fields:
            self.test_field.addItem(f"{label}  ({key})", key)
        self.test_unit = QLineEdit()
        self.test_unit.setToolTip("LAN readings use the same raw values as Measurements. Unit is a label; it does not rescale input.")
        self.test_expected = QLineEdit()
        self.test_expected.setPlaceholderText("Optional, required for tolerance filter")
        form.addRow("Test ID", self.test_id)
        form.addRow("Measurement source", self.test_source)
        form.addRow("Report field", self.test_field)
        form.addRow("Unit", self.test_unit)
        form.addRow("Expected value", self.test_expected)
        edit.addWidget(details)

        filters = QGroupBox("Acceptance filters (all must pass)")
        filter_body = QVBoxLayout(filters)
        self.filter_list_layout = QVBoxLayout()
        filter_body.addLayout(self.filter_list_layout)
        add_filter = QPushButton("+ Add filter")
        add_filter.clicked.connect(self._add_filter)
        filter_body.addWidget(add_filter, 0, Qt.AlignmentFlag.AlignLeft)
        edit.addWidget(filters)
        explanation = QLabel(
            'Sources: analog.*, binary.*, counters.*, external.* or emwolf.scenario_N.*. '
            'Values: true/false, 50, or "text". Manual filters never auto-pass.'
        )
        explanation.setObjectName("muted")
        explanation.setWordWrap(True)
        edit.addWidget(explanation)
        edit.addStretch()
        scroll.setWidget(scroll_body)
        body.addWidget(scroll, 1)
        root.addLayout(body, 1)

        actions = QHBoxLayout()
        preview = QPushButton("Preview JSON")
        preview.clicked.connect(self._preview)
        actions.addWidget(preview)
        actions.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        root.addLayout(actions)

    def _refresh_tests(self, index: int) -> None:
        blocked = self.tests_list.blockSignals(True)
        self.tests_list.clear()
        for test in self._draft["tests"]:
            self.tests_list.addItem(f"{test['id']}\n{test['report_field']}")
        self.tests_list.setCurrentRow(index)
        self.tests_list.blockSignals(blocked)
        self._selected_index = index
        self._display_test(index)

    def _display_test(self, index: int) -> None:
        test = self._draft["tests"][index]
        self.test_id.setText(test["id"])
        self.test_source.setEditText(test["source"])
        self.test_field.setCurrentIndex(self.test_field.findData(test["report_field"]))
        self.test_unit.setText(test.get("unit", ""))
        self.test_expected.setText(str(test["expected"]) if "expected" in test else "")
        self._clear_filters()
        for data in test["filters"]:
            self._append_filter(data)

    def _clear_filters(self) -> None:
        for row in self._filter_rows:
            self.filter_list_layout.removeWidget(row)
            row.deleteLater()
        self._filter_rows.clear()

    def _append_filter(self, data: dict) -> None:
        row = _FilterRow(data, len(self._filter_rows), self.model.currentText(), self._build)
        row.remove_requested.connect(self._remove_filter)
        self._filter_rows.append(row)
        self.filter_list_layout.addWidget(row)

    def _model_changed(self, model: str) -> None:
        _fill_sources(self.test_source, model, self._build)
        for row in self._filter_rows:
            row.model = model
            for widget, kind in row.params.values():
                if kind == "source":
                    _fill_sources(widget, model, self._build)

    def _capture_selected(self) -> None:
        if self._selected_index is None:
            return
        test = self._draft["tests"][self._selected_index]
        test_id = self.test_id.text().strip()
        source = self.test_source.currentText().strip()
        field = self.test_field.currentData()
        if not test_id or not source or not field:
            raise ValueError("Test ID, measurement source and report field are required")
        filters = [row.value() for row in self._filter_rows]
        if not filters:
            raise ValueError("Each test needs at least one filter")
        expected_text = self.test_expected.text().strip()
        expected = _number(expected_text, "Expected value") if expected_text else None
        test.update(id=test_id, source=source, report_field=field, filters=filters)
        if self.test_unit.text().strip():
            test["unit"] = self.test_unit.text().strip()
        else:
            test.pop("unit", None)
        if expected is None:
            test.pop("expected", None)
        else:
            test["expected"] = expected

    def _capture_lot(self) -> dict:
        self._capture_selected()
        lot = copy.deepcopy(self._draft)
        lot["lot_id"] = self.lot_id.text().strip()
        lot["device_model"] = self.model.currentText()
        lot["max_age_seconds"] = _number(self.max_age.text(), "Max data age")
        return validate_lot(lot, self._allowed)

    def _selected_test_changed(self, index: int) -> None:
        if index < 0 or index == self._selected_index:
            return
        try:
            self._capture_selected()
        except ValueError as exc:
            self._warn(exc)
            self.tests_list.blockSignals(True)
            self.tests_list.setCurrentRow(self._selected_index if self._selected_index is not None else 0)
            self.tests_list.blockSignals(False)
            return
        self._selected_index = index
        self._display_test(index)
        self._refresh_test_labels()

    def _refresh_test_labels(self) -> None:
        for index, test in enumerate(self._draft["tests"]):
            self.tests_list.item(index).setText(f"{test['id']}\n{test['report_field']}")

    def _add_test(self) -> None:
        try:
            self._capture_selected()
            self._draft["tests"].append(self._new_test(self._draft["tests"], len(self._draft["tests"]) + 1))
            self._refresh_tests(len(self._draft["tests"]) - 1)
        except ValueError as exc:
            self._warn(exc)

    def _remove_test(self) -> None:
        if len(self._draft["tests"]) == 1:
            QMessageBox.information(self, "Test Lot", "A lot must have at least one test.")
            return
        index = self._selected_index
        if index is None:
            return
        self._draft["tests"].pop(index)
        self._refresh_tests(min(index, len(self._draft["tests"]) - 1))

    def _add_filter(self) -> None:
        if len(self._filter_rows) >= 16:
            QMessageBox.information(self, "Filter limit", "A test supports at most 16 filters.")
            return
        self._append_filter({"type": "manual"})

    def _remove_filter(self, row: _FilterRow) -> None:
        if len(self._filter_rows) == 1:
            QMessageBox.information(self, "Test filters", "A test needs at least one filter.")
            return
        self.filter_list_layout.removeWidget(row)
        self._filter_rows.remove(row)
        row.deleteLater()
        for i, item in enumerate(self._filter_rows):
            item.setTitle(f"Filter {i + 1}")

    def _preview(self) -> None:
        try:
            lot = self._capture_lot()
        except (ValueError, TypeError) as exc:
            self._warn(exc)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Validated Test Lot JSON")
        dialog.resize(760, 550)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(json.dumps(lot, indent=2, ensure_ascii=False))
        layout.addWidget(editor)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def _save(self) -> None:
        try:
            self.lot = self._capture_lot()
        except (ValueError, TypeError) as exc:
            self._warn(exc)
            return
        self.accept()

    def _warn(self, error: Exception) -> None:
        QMessageBox.warning(self, "Invalid Test Lot", str(error))
