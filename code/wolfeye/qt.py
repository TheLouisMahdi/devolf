"""Small Qt 5/6 compatibility boundary for the shared Windows codebase."""

from __future__ import annotations

try:
    from PySide6 import QtCore, QtGui, QtWidgets

    QT_API = "PySide6"
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

    QT_API = "PySide2"


IS_QT6 = QT_API == "PySide6"


def _symbol(name: str):
    for module in (QtCore, QtGui, QtWidgets):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)


def __getattr__(name: str):
    return _symbol(name)


def _add_enum_scope(owner, scope_name: str) -> None:
    """Expose Qt 6 scoped-enum spelling when running with PySide2."""
    if not hasattr(owner, scope_name):
        setattr(owner, scope_name, owner)


if not IS_QT6:
    Qt = QtCore.Qt
    for scope in (
        "AlignmentFlag",
        "ApplicationAttribute",
        "AspectRatioMode",
        "CheckState",
        "CursorShape",
        "DockWidgetArea",
        "FocusPolicy",
        "HighDpiScaleFactorRoundingPolicy",
        "ItemDataRole",
        "ItemFlag",
        "KeyboardModifier",
        "MouseButton",
        "PenStyle",
        "ScrollBarPolicy",
        "TransformationMode",
    ):
        _add_enum_scope(Qt, scope)

    for owner_name, scopes in (
        ("QAbstractItemView", ("EditTrigger", "SelectionBehavior", "SelectionMode")),
        ("QAbstractSpinBox", ("ButtonSymbols",)),
        ("QDockWidget", ("DockWidgetFeature",)),
        ("QEvent", ("Type",)),
        ("QFormLayout", ("FieldGrowthPolicy",)),
        ("QFrame", ("Shape",)),
        ("QHeaderView", ("ResizeMode",)),
        ("QMessageBox", ("StandardButton",)),
        ("QPainter", ("RenderHint",)),
        ("QPlainTextEdit", ("LineWrapMode",)),
        ("QTableWidget", ("EditTrigger", "ScrollMode")),
    ):
        owner = _symbol(owner_name)
        for scope in scopes:
            _add_enum_scope(owner, scope)

    application = QtWidgets.QApplication
    if not hasattr(application, "exec"):
        application.exec = application.exec_


def configure_high_dpi() -> None:
    """Enable equivalent high-DPI behavior before QApplication is created."""
    application = QtWidgets.QApplication
    qt = QtCore.Qt
    application_attributes = getattr(qt, "ApplicationAttribute", qt)
    application.setAttribute(application_attributes.AA_DontUseNativeDialogs, True)
    if not IS_QT6:
        application.setAttribute(application_attributes.AA_EnableHighDpiScaling, True)
        application.setAttribute(application_attributes.AA_UseHighDpiPixmaps, True)
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
