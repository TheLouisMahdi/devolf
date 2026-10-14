"""One WI03 test mode with visible conditions, units and recorded evidence."""
from __future__ import annotations

import copy
from datetime import datetime

from wolfeye.qt import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                        QHeaderView, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
                        QTimer, QVBoxLayout, Qt)
from wolfeye.services.fc22_instruction import evaluate_case, native_readings


class InstructionDialog(QDialog):
    def __init__(self, catalog: dict, case: dict, model: str, snapshot_provider, previous=None, parent=None):
        super().__init__(parent)
        self.catalog, self.case, self.model = catalog, case, model
        self.snapshot_provider = snapshot_provider
        self.record = None
        self._native = {}
        self._controls = {}
        self.setWindowTitle(f"WI03 · {case['board']} · {case['title']}")
        self.resize(1040, 720)
        layout = QVBoxLayout(self)
        doc = catalog["document"]
        heading = QLabel(f"{doc['code']} revision {doc['revision']} · pages {', '.join(map(str, case['pages']))} · DUT {model}")
        layout.addWidget(heading)
        setup = QLabel(case["setup"])
        setup.setWordWrap(True)
        setup.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(setup)
        inputs = "\n".join(f"{row['label']}: {row['source_expression']}" for row in case.get("inputs", []))
        if case.get("reference"):
            for key, value in case["reference"].items():
                if isinstance(value, dict):
                    value = value.get("source_expression") or (
                        f"{value['value']} {value.get('unit', '')}" if "value" in value else "See the displayed reply example"
                    )
                elif isinstance(value, list):
                    value = ", ".join(map(str, value))
                inputs += f"\n{key.replace('_', ' ').capitalize()}: {value}"
        reference = QLabel(inputs or "Use the setup and qualitative conditions above. WI03 specifies no additional numeric stimulus for this mode.")
        reference.setWordWrap(True)
        reference.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(reference)
        self.confirm_setup = QCheckBox("The specified input values and setup conditions have been established")
        layout.addWidget(self.confirm_setup)
        self.live = QCheckBox("Use current DUT measurements where a verified unit conversion is available")
        self.live.setChecked(snapshot_provider() is not None)
        layout.addWidget(self.live)
        self.table = QTableWidget(len(case["checks"]), 5)
        self.table.setHorizontalHeaderLabels(("Parameter", "WI03 acceptance", "Measured value", "Unit", "Result"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column in (3, 4):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for index, row in enumerate(case["checks"]):
            self.table.setItem(index, 0, QTableWidgetItem(row["label"]))
            criterion = QTableWidgetItem(row["source_expression"])
            criterion.setToolTip(row.get("requires_review", "Exact acceptance condition from WI03"))
            self.table.setItem(index, 1, criterion)
            self.table.setItem(index, 3, QTableWidgetItem(row["unit"]))
            self.table.setItem(index, 4, QTableWidgetItem("NOT_TESTED"))
            if row["unit"] == "boolean":
                control = QComboBox()
                control.addItem("Not observed", None)
                control.addItem("True", True)
                control.addItem("False", False)
                control.currentIndexChanged.connect(self._evaluate)
            else:
                control = QLineEdit()
                control.setPlaceholderText(f"Measured {row['unit']}")
                control.textChanged.connect(self._evaluate)
            self._controls[row["id"]] = control
            self.table.setCellWidget(index, 2, control)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.confirm_setup.toggled.connect(self._evaluate)
        self.live.toggled.connect(self._update_native)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._update_native)
        self.timer.start()
        self._update_native()

    def _update_native(self, *_args) -> None:
        current = self.snapshot_provider() if self.live.isChecked() else None
        self._native = native_readings(self.case, current[1]) if current and current[0] == self.model else {}
        for row in self.case["checks"]:
            if not row.get("binding"):
                continue
            control = self._controls[row["id"]]
            auto = self.live.isChecked()
            control.blockSignals(True)
            if row["unit"] == "boolean":
                control.setEnabled(not auto)
                if auto:
                    control.setCurrentIndex(control.findData(self._native.get(row["id"], {}).get("value")))
            else:
                control.setReadOnly(auto)
                if auto:
                    value = self._native.get(row["id"], {}).get("value")
                    control.setText("" if value is None else str(value))
            control.blockSignals(False)
        self._evaluate()

    def _readings(self) -> dict:
        values = {}
        for row in self.case["checks"]:
            if self.live.isChecked() and row.get("binding"):
                if row["id"] in self._native:
                    values[row["id"]] = self._native[row["id"]]
                continue
            control = self._controls[row["id"]]
            value = control.currentData() if row["unit"] == "boolean" else control.text().strip() or None
            if value is not None:
                values[row["id"]] = {"value": value, "unit": row["unit"], "source": "operator observation",
                                      "input_kind": "manual", "timestamp": datetime.now().astimezone().isoformat()}
        return values

    def _evaluate(self, *_args) -> dict:
        # Cell signals can fire while constructing the table.
        if not hasattr(self, "summary"):
            return {}
        results = evaluate_case(self.case, self._readings(), setup_confirmed=self.confirm_setup.isChecked(), model=self.model)
        for index, row in enumerate(self.case["checks"]):
            result = results[row["id"]]
            item = self.table.item(index, 4)
            item.setText(result["status"])
            item.setToolTip(result["reason"])
        counts = {status: sum(r["status"] == status for r in results.values()) for status in ("PASS", "FAIL", "NOT_TESTED", "INVALID")}
        self.summary.setText(" · ".join(f"{count} {status}" for status, count in counts.items()) +
                             "\nManual observations are recorded as manual. Ambiguous or unspecified limits remain NOT_TESTED.")
        return results

    def _save(self) -> None:
        self._update_native()
        self.record = {"document": copy.deepcopy(self.catalog["document"]), "case": copy.deepcopy(self.case),
                       "model": self.model, "setup_confirmed": self.confirm_setup.isChecked(),
                       "recorded_at": datetime.now().astimezone().isoformat(), "results": self._evaluate()}
        self.accept()
