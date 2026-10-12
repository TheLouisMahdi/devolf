from __future__ import annotations

from pathlib import Path


V2_STYLE_SHEET = """
QWidget {
    color: #18242d;
    background: #eef2f5;
    font-family: "Segoe UI";
    font-size: 9pt;
}
QLabel, QCheckBox, QRadioButton { background: transparent; }
QMainWindow, QDialog { background: #eef2f5; }
QFrame#brandBar {
    background: #ffffff;
    border: 1px solid #ccd5dc;
    border-left: 4px solid #087abb;
    border-radius: 5px;
}
QLabel#v2Title {
    color: #10212d;
    font-size: 15pt;
    font-weight: 700;
}
QLabel#v2Subtitle { color: #60717d; font-size: 9pt; }
QLabel#v2Badge {
    color: #ffffff;
    background: #087abb;
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 8pt;
    font-weight: 600;
}
QLabel#protectionDeviceBadge {
    color: #ffffff;
    background: #334852;
    border-left: 4px solid #16a0d4;
    border-radius: 4px;
    padding: 4px 9px;
    font-size: 8pt;
    font-weight: 700;
}
QLabel#tccTitle { color: #10212d; font-size: 14pt; font-weight: 700; }
QLabel#tccResult {
    color: #ffffff;
    background: #087abb;
    border-radius: 4px;
    padding: 8px;
    font-weight: 700;
}
QWidget#tccSidebar {
    background: #ffffff;
    border: 1px solid #ccd5dc;
    border-radius: 5px;
    min-width: 240px;
    max-width: 275px;
}
QGroupBox, QFrame#card {
    background: #ffffff;
    border: 1px solid #ccd5dc;
    border-radius: 5px;
}
QGroupBox { margin-top: 9px; padding: 11px 7px 7px 7px; }
QGroupBox::title {
    subcontrol-origin: margin;
    left: 9px;
    padding: 0 4px;
    color: #244556;
    font-weight: 600;
}
QLabel#muted, QStatusBar { color: #647580; }
QLabel#metricTitle { color: #60717d; font-size: 8pt; font-weight: 600; }
QLabel#metricValue { color: #087abb; font-size: 16pt; font-weight: 700; }
QLabel#connected { color: #18864b; font-weight: 600; }
QLabel#disconnected { color: #7d2525; font-weight: 600; }
QPushButton {
    color: #17313f;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff, stop:1 #e8eef2
    );
    border: 1px solid #9eafb9;
    border-bottom-color: #82959f;
    border-radius: 6px;
    padding: 5px 13px;
    min-height: 22px;
    font-weight: 600;
}
QPushButton:hover {
    color: #075f91;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #f8fcff, stop:1 #d9effa
    );
    border-color: #2e8fbd;
}
QPushButton:pressed {
    color: #064f76;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #c7e3f1, stop:1 #e5f3fa
    );
    border-color: #087abb;
    padding-top: 6px;
    padding-bottom: 4px;
}
QPushButton:focus {
    border: 2px solid #168dcc;
    padding: 4px 12px;
}
QPushButton:disabled {
    color: #8b979f;
    background: #e8ecef;
    border-color: #cfd7dc;
}

QPushButton#primary {
    color: #ffffff;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #1496d4, stop:1 #0871ad
    );
    border-color: #066697;
    border-bottom-color: #05577f;
    font-weight: 700;
}
QPushButton#primary:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #22a6e2, stop:1 #087abb
    );
    border-color: #065f8d;
}
QPushButton#primary:pressed {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #066da2, stop:1 #128ac3
    );
}

QPushButton#danger {
    color: #9d2930;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #fffdfd, stop:1 #f8e6e7
    );
    border-color: #cf8f94;
}
QPushButton#danger:hover {
    color: #ffffff;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #d95b62, stop:1 #b9363d
    );
    border-color: #a82e34;
}

QPushButton#success {
    color: #146d3b;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #fbfffc, stop:1 #e0f3e8
    );
    border-color: #80bc99;
}
QPushButton#success:hover {
    color: #ffffff;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #35a968, stop:1 #18834a
    );
    border-color: #14723f;
}

QPushButton#tccElementButton {
    color: #087abb;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff, stop:1 #eaf5fa
    );
    border-color: #8fbcd3;
    font-weight: 700;
    text-align: left;
}
QPushButton#tccElementButton:hover {
    color: #ffffff;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #1496d4, stop:1 #0871ad
    );
    border-color: #087abb;
}

QToolButton {
    color: #17313f;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff, stop:1 #e7edf1
    );
    border: 1px solid #9eafb9;
    border-bottom-color: #82959f;
    border-radius: 5px;
    padding: 4px 8px;
    min-width: 24px;
    min-height: 21px;
    font-weight: 600;
}
QToolButton:hover {
    color: #087abb;
    background: #e2f2fa;
    border-color: #2e8fbd;
}
QToolButton:pressed,
QToolButton:checked {
    color: #ffffff;
    background: #087abb;
    border-color: #05689b;
}
QToolButton:disabled {
    color: #929da4;
    background: #e8ecef;
    border-color: #cfd7dc;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    color: #17242d;
    background: #ffffff;
    border: 1px solid #aebbc4;
    border-radius: 3px;
    selection-background-color: #087abb;
    selection-color: #ffffff;
    min-height: 19px;
}
QLineEdit, QComboBox { padding: 3px 7px; }
QSpinBox, QDoubleSpinBox { min-width: 112px; padding: 3px 27px 3px 7px; }
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { border-color: #5f9fbe; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 2px solid #087abb; }

QComboBox::drop-down {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #f7fafc, stop:1 #e4eaee
    );
    border-left: 1px solid #aebbc4;
    border-top-right-radius: 3px;
    border-bottom-right-radius: 3px;
}
QComboBox::drop-down:hover { background: #dceff8; }
QComboBox::down-arrow {
    image: url("__COMBO_ARROW__");
    width: 10px;
    height: 7px;
}

QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 22px;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff, stop:1 #e8edf1
    );
    border-left: 1px solid #aebbc4;
    border-bottom: 1px solid #c4cfd5;
    border-top-right-radius: 3px;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 22px;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #f3f6f8, stop:1 #dfe6ea
    );
    border-left: 1px solid #aebbc4;
    border-top: 1px solid #ffffff;
    border-bottom-right-radius: 3px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: #dceff8;
    border-left-color: #5f9fbe;
}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {
    background: #bfddea;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("__SPIN_UP__");
    width: 8px;
    height: 5px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("__SPIN_DOWN__");
    width: 8px;
    height: 5px;
}
QTabWidget::pane { background: #ffffff; border: 1px solid #bdc9d1; top: -1px; }
QTabBar::tab {
    color: #314753;
    background: #dde4e9;
    border: 1px solid #bdc9d1;
    border-bottom: 0;
    padding: 7px 15px;
    min-width: 80px;
}
QTabBar::tab:hover { background: #e9f4fa; color: #087abb; }
QTabBar::tab:selected { color: #ffffff; background: #087abb; border-color: #087abb; font-weight: 600; }
QHeaderView::section {
    color: #ffffff;
    background: #334852;
    padding: 6px;
    border: 0;
    border-right: 1px solid #536975;
}
QTableWidget, QListWidget {
    color: #18242d;
    background: #ffffff;
    alternate-background-color: #f3f7f9;
    gridline-color: #d5dde2;
    border: 1px solid #aebbc4;
    selection-background-color: #1686c1;
    selection-color: #ffffff;
}
QTableWidget::item { padding: 3px 5px; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #e7ecef; width: 13px; margin: 0; }
QScrollBar::handle:vertical { background: #93a5b0; border-radius: 5px; min-height: 28px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #087abb; }
QScrollBar:horizontal { background: #e7ecef; height: 13px; }
QScrollBar::handle:horizontal { background: #93a5b0; border-radius: 5px; min-width: 28px; margin: 2px; }
QPlainTextEdit {
    color: #d7e6ee;
    background: #17232b;
    border: 1px solid #40545f;
    border-radius: 3px;
    font-family: "Cascadia Mono", Consolas;
    selection-background-color: #087abb;
}
QMenuBar { color: #253843; background: #ffffff; border-bottom: 1px solid #ccd5dc; }
QMenuBar::item { padding: 6px 10px; background: transparent; }
QMenuBar::item:selected, QMenu::item:selected { color: #ffffff; background: #087abb; }
QMenu { color: #253843; background: #ffffff; border: 1px solid #aebbc4; }
QDockWidget { color: #ffffff; background: #334852; font-weight: 600; }
QDockWidget::title { background: #334852; padding: 6px; text-align: left; }
QStatusBar { background: #ffffff; border-top: 1px solid #ccd5dc; }
QToolTip { color: #ffffff; background: #20323c; border: 1px solid #087abb; padding: 4px; }
QSplitter::handle { background: #bdc9d1; width: 2px; }
"""


V2_EMWOLF_STYLE = """
QWidget#emwolfPage QLineEdit,
QWidget#emwolfPage QSpinBox,
QWidget#emwolfPage QComboBox {
    color: #18242d;
    background: #ffffff;
    border-color: #9babb5;
}
QWidget#emwolfPage QLineEdit:focus,
QWidget#emwolfPage QSpinBox:focus,
QWidget#emwolfPage QComboBox:focus { border-color: #087abb; }
QWidget#emwolfPage QComboBox::drop-down {
    background: #e1e8ec;
    border-left-color: #9babb5;
}
QWidget#emwolfPage QTableWidget#scenarioTable QHeaderView::section {
    color: #ffffff;
    background: #334852;
}
"""


V2_COMPACT_STYLE = """
QGroupBox { margin-top: 7px; padding: 8px 5px 5px 5px; }
QTabBar::tab { padding: 5px 10px; min-width: 68px; }
QPushButton { padding: 4px 10px; min-height: 20px; }
QPushButton:focus { padding: 3px 9px; }
QToolButton { padding: 3px 7px; min-height: 19px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    min-height: 17px;
}
QLineEdit, QComboBox { padding: 2px 6px; }
QSpinBox, QDoubleSpinBox { padding: 2px 28px 2px 6px; }
QHeaderView::section { padding: 4px; }
QTableWidget::item { padding: 2px 4px; }
"""


V2_EMWOLF_COMPACT_STYLE = """
QWidget#emwolfPage QLineEdit,
QWidget#emwolfPage QSpinBox {
    min-height: 16px;
}
QWidget#emwolfPage QLineEdit { padding: 1px 6px; }
QWidget#emwolfPage QSpinBox { padding: 1px 28px 1px 6px; }
QWidget#emwolfPage QComboBox {
    padding: 1px 22px 1px 6px;
    min-height: 16px;
}
QWidget#emwolfPage QSpinBox:focus { padding: 0 27px 0 5px; }
QWidget#emwolfPage QLineEdit:focus { padding: 0 5px; }
QWidget#emwolfPage QComboBox:focus { padding: 0 21px 0 5px; }
QWidget#emwolfPage QSpinBox#portSpin { padding: 1px 6px; }
QWidget#emwolfPage QSpinBox#portSpin:focus { padding: 0 5px; }
QWidget#emwolfPage QCheckBox::indicator { width: 14px; height: 14px; }
"""

def build_v2_style_sheet(assets_dir: str | Path) -> str:
    """Return the global UI stylesheet with cross-Windows SVG controls."""
    assets = Path(assets_dir).resolve().as_posix()
    return (
        V2_STYLE_SHEET
        .replace("__COMBO_ARROW__", f"{assets}/combo-arrow.svg")
        .replace("__SPIN_UP__", f"{assets}/spin-up.svg")
        .replace("__SPIN_DOWN__", f"{assets}/spin-down.svg")
    )
