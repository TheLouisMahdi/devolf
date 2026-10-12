"""Qt 6 imports and shared UI helpers."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

QT_API = "PySide6"
IS_QT6 = True


def _symbol(name: str):
    for module in (QtCore, QtGui, QtWidgets):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)


def __getattr__(name: str):
    return _symbol(name)


def configure_high_dpi() -> None:
    """Enable equivalent high-DPI behavior before QApplication is created."""
    application = QtWidgets.QApplication
    qt = QtCore.Qt
    application_attributes = getattr(qt, "ApplicationAttribute", qt)
    application.setAttribute(application_attributes.AA_DontUseNativeDialogs, True)
    rounding_policy = getattr(qt, "HighDpiScaleFactorRoundingPolicy", None)
    setter = getattr(application, "setHighDpiScaleFactorRoundingPolicy", None)
    if rounding_policy is not None and setter is not None:
        setter(rounding_policy.PassThrough)


def event_position(event):
    """Return a floating-point local event position on Qt 5 and Qt 6."""
    position = getattr(event, "position", None)
    if position is not None:
        return position()
    local_position = getattr(event, "localPos", None)
    if local_position is not None:
        return local_position()
    return QtCore.QPointF(event.pos())
