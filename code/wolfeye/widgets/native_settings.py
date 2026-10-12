from __future__ import annotations

from copy import deepcopy
from typing import Any

from wolfeye.qt import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)


class NativeSettingsPage(QWidget):
    """Lossless editor for the JSON exposed by the original C++ Settings ABI."""

    changed = Signal()
    PATH_ROLE = Qt.ItemDataRole.UserRole
    TYPE_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self) -> None:
        super().__init__()
        self._settings: dict[str, Any] = {}
        self._loading = False

        root = QVBoxLayout(self)
        note = QLabel(
            "Exact company Settings ABI. Values are decoded and encoded by the original "
            "C++ Configure/Settings implementation; device writes preserve all untouched "
            "wire bytes exactly."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        root.addWidget(note)

        tools = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by native path or value…")
        expand = QPushButton("Expand all")
        collapse = QPushButton("Collapse all")
        tools.addWidget(self.filter, 1)
        tools.addWidget(expand)
        tools.addWidget(collapse)
        root.addLayout(tools)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(("Company setting", "Value", "Type"))
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 420)
        self.tree.setColumnWidth(1, 240)
        root.addWidget(self.tree, 1)

        self.filter.textChanged.connect(self._apply_filter)
        expand.clicked.connect(self.tree.expandAll)
        collapse.clicked.connect(self.tree.collapseAll)
        self.tree.itemChanged.connect(self._item_changed)

    def set_settings(self, settings: dict[str, Any]) -> None:
        self._settings = deepcopy(settings)
        self._loading = True
        self.tree.clear()
        self._append_children(None, self._settings, ())
        self.tree.expandToDepth(1)
        self._loading = False
        self._apply_filter(self.filter.text())

    def settings(self) -> dict[str, Any]:
        result = deepcopy(self._settings)
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value() is not None:
            item = iterator.value()
            path = item.data(0, self.PATH_ROLE)
            kind = item.data(0, self.TYPE_ROLE)
            if path is not None and kind:
                self._set_path(result, tuple(path), self._parse(item.text(1), kind))
            iterator += 1
        return result

    def _append_children(
        self,
        parent: QTreeWidgetItem | None,
        value: Any,
        path: tuple[str | int, ...],
    ) -> None:
        entries = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in entries:
            title = f"[{key}]" if isinstance(key, int) else str(key)
            item = QTreeWidgetItem([title, "", self._type_name(child)])
            full_path = path + (key,)
            item.setToolTip(0, self._format_path(full_path))
            if isinstance(child, (dict, list)):
                item.setFirstColumnSpanned(False)
                self._append_children(item, child, full_path)
            else:
                item.setText(1, self._format(child))
                item.setData(0, self.PATH_ROLE, list(full_path))
                item.setData(0, self.TYPE_ROLE, self._type_name(child))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if not self._loading and column == 1 and item.data(0, self.PATH_ROLE) is not None:
            self.changed.emit()

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold().strip()

        def visit(item: QTreeWidgetItem) -> bool:
            child_visible = any(visit(item.child(i)) for i in range(item.childCount()))
            own = needle in (
                item.toolTip(0) + " " + item.text(0) + " " + item.text(1)
            ).casefold()
            visible = not needle or own or child_visible
            item.setHidden(not visible)
            if needle and visible and item.childCount():
                item.setExpanded(True)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    @staticmethod
    def _type_name(value: Any) -> str:
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return f"array[{len(value)}]"
        if isinstance(value, dict):
            return "object"
        raise TypeError(f"Unsupported company setting type: {type(value).__name__}")

    @staticmethod
    def _format(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _format_path(path: tuple[str | int, ...]) -> str:
        result = ""
        for part in path:
            result += f"[{part}]" if isinstance(part, int) else ("." if result else "") + part
        return result

    @staticmethod
    def _parse(text: str, kind: str) -> Any:
        value = text.strip()
        if kind == "bool":
            normalized = value.casefold()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
            raise ValueError(f"Invalid boolean value: {text}")
        if kind == "int":
            return int(value, 10)
        if kind == "float":
            return float(value)
        return text

    @staticmethod
    def _set_path(root: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
        target: Any = root
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
