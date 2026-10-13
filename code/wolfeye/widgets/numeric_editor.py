"""Shared numeric editor setup and preservation of unchanged loaded values."""
from __future__ import annotations

from typing import Any
from wolfeye.numeric_schema import numeric_spec
from wolfeye.qt import QDoubleSpinBox, QSpinBox


def configure_numeric_editor(widget: QSpinBox | QDoubleSpinBox, path: str) -> None:
    spec = numeric_spec(path)
    if spec is None:
        return
    if isinstance(widget, QDoubleSpinBox):
        widget.setDecimals(spec.decimals)
        widget.setSingleStep(10 ** -spec.decimals)
    if isinstance(widget, QSpinBox):
        widget.setRange(int(spec.minimum), int(spec.maximum))
    else:
        widget.setRange(spec.minimum, spec.maximum)
    widget.setProperty("numericInteger", spec.decimals == 0)
    widget.setToolTip(f"{path}\nStored as {spec.storage}, scale {spec.scale}.\n"
                      f"Editable range: {spec.minimum:g} to {spec.maximum:g}")


def set_numeric_value(widget: QSpinBox | QDoubleSpinBox, value: Any) -> None:
    widget.setValue(value)
    widget.setProperty("loadedNumericValue", value)
    widget.setProperty("loadedNumericDisplay", widget.value())


def numeric_value(widget: QSpinBox | QDoubleSpinBox) -> int | float:
    value = widget.value()
    if widget.property("loadedNumericDisplay") == value:
        return widget.property("loadedNumericValue")
    return int(value) if widget.property("numericInteger") else value
