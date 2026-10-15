"""Presentation for FC22 inspection: compact steps and one editable test table."""
from __future__ import annotations

from wolfeye.qt import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QProgressBar, QPushButton, QScrollArea,
    QSize, QSizePolicy, QTableWidget, QVBoxLayout, QWidget, Qt,
)


SECTION_NAMES = {
    "voltages": "Voltages", "currents": "Currents", "measurements": "Power",
    "freq_pf": "Frequency & PF", "supply": "Supply & sensors",
    "digital_outputs": "Digital outputs", "digital_inputs": "Digital inputs",
    "internal_modem": "Internal modem", "fault_battery": "Fault & battery",
    "ar_parameters": "AR parameters", "leds": "LEDs",
}

STYLE = """
QWidget#fc22TesterPage { background: #f2f5f8; }
QWidget#fc22TesterPage QLabel { background: transparent; }
QWidget#fc22TesterPage QWidget#testerValueCell,
QWidget#fc22TesterPage QWidget#testerFormCell { background: transparent; }
QWidget#fc22TesterPage QFrame#testerHeader,
QWidget#fc22TesterPage QFrame#testerToolbar {
    background: #ffffff; border: 1px solid #dce4eb; border-radius: 9px;
}
QWidget#fc22TesterPage QLabel#testerTitle { color: #193549; font-size: 14pt; font-weight: 700; }
QWidget#fc22TesterPage QLabel#testerSubtitle,
QWidget#fc22TesterPage QLabel#muted { color: #687d8c; }
QWidget#fc22TesterPage QLabel#testerSectionTitle { color: #193549; font-size: 11pt; font-weight: 700; }
QWidget#fc22TesterPage QLabel#testerConnection {
    color: #536b7a; background: #eef3f7; border-radius: 9px; padding: 5px 10px; font-weight: 600;
}
QWidget#fc22TesterPage QLabel#testerConnection[online="true"] { color: #187449; background: #e7f5ed; }
QWidget#fc22TesterPage QGroupBox {
    background: #ffffff; border: 1px solid #dce4eb; border-radius: 9px;
    margin-top: 10px; padding: 13px 10px 10px;
}
QWidget#fc22TesterPage QGroupBox::title { color: #304d60; padding: 0 5px; left: 12px; }
QWidget#fc22TesterPage QPushButton {
    background: #ffffff; color: #29485e; border: 1px solid #cbd8e2;
    border-radius: 6px; min-height: 24px; padding: 4px 12px;
}
QWidget#fc22TesterPage QPushButton:hover { background: #edf6fc; border-color: #81b6d6; }
QWidget#fc22TesterPage QPushButton:focus { border: 1px solid #168dcc; padding: 4px 12px; }
QWidget#fc22TesterPage QPushButton:disabled { color: #99a8b4; background: #f3f5f7; border-color: #e0e7ed; }
QWidget#fc22TesterPage QPushButton#primary { background: #127fb9; color: #ffffff; border-color: #127fb9; }
QWidget#fc22TesterPage QPushButton#primary:hover { background: #076da6; }
QWidget#fc22TesterPage QPushButton#testerStep { text-align: left; background: #e8eef4; border-color: transparent; }
QWidget#fc22TesterPage QPushButton#testerStep:checked { color: #ffffff; background: #127fb9; border-color: #127fb9; }
QWidget#fc22TesterPage QPushButton#testerCapture:checked { color: #9e3842; background: #fff0f0; border-color: #e3b9be; }
QWidget#fc22TesterPage QLineEdit, QWidget#fc22TesterPage QComboBox {
    background: #ffffff; border: 1px solid #ccd9e3; border-radius: 5px;
    min-height: 22px; padding: 3px 8px; selection-background-color: #1686c1;
}
QWidget#fc22TesterPage QLineEdit:focus, QWidget#fc22TesterPage QComboBox:focus { border: 1px solid #168dcc; }
QWidget#fc22TesterPage QLineEdit[readOnly="true"] { color: #34566f; background: #f0f6fb; border-color: #e1eaf1; }
QWidget#fc22TesterPage QComboBox:disabled { color: #8294a0; background: #f3f6f8; border-color: #e1eaf1; }
QWidget#fc22TesterPage QListWidget { background: #ffffff; border: 0; outline: none; }
QWidget#fc22TesterPage QListWidget::item { border-radius: 5px; padding: 2px 7px; margin: 1px 0; }
QWidget#fc22TesterPage QListWidget::item:selected { color: #086aa2; background: #e6f2fb; }
QWidget#fc22TesterPage QListWidget::item:hover:!selected { background: #f0f5f9; }
QWidget#fc22TesterPage QTableWidget {
    background: #ffffff; alternate-background-color: #f8fafc; border: 1px solid #dce4eb;
    border-radius: 7px; selection-background-color: #edf5fb; selection-color: #24465d;
    gridline-color: #eef2f6;
}
QWidget#fc22TesterPage QTableWidget::item { padding: 5px 8px; border: 0; }
QWidget#fc22TesterPage QHeaderView::section {
    background: #edf2f7; color: #5b7182; border: 0; border-bottom: 1px solid #dce4eb;
    padding: 9px 8px; font-weight: 600;
}
QWidget#fc22TesterPage QLabel#testerResult { padding: 3px 8px; border-radius: 5px; color: #738695; }
QWidget#fc22TesterPage QLabel#testerResult[state="PASS"],
QWidget#fc22TesterPage QLabel#testerCount[state="PASS"] { color: #167144; background: #e9f6ee; }
QWidget#fc22TesterPage QLabel#testerResult[state="FAIL"],
QWidget#fc22TesterPage QLabel#testerCount[state="FAIL"] { color: #b43743; background: #fcecee; }
QWidget#fc22TesterPage QLabel#testerCount {
    color: #667d8e; background: #e9eff4; border-radius: 5px; padding: 5px 9px; font-weight: 600;
}
QWidget#fc22TesterPage QProgressBar { border: 0; background: #dfe9f1; border-radius: 3px; max-height: 6px; }
QWidget#fc22TesterPage QProgressBar::chunk { background: #2894c9; border-radius: 3px; }
"""


def _caption(text: str, name: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def _scroll_body():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 3, 0)
    layout.setSpacing(10)
    scroll.setWidget(body)
    return scroll, layout


def _cell(label: str, widget: QWidget) -> QWidget:
    cell = QWidget()
    cell.setObjectName("testerFormCell")
    layout = QVBoxLayout(cell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    layout.addWidget(_caption(label))
    layout.addWidget(widget)
    return cell


def _button(text, callback, primary=False):
    button = QPushButton(text)
    if primary:
        button.setObjectName("primary")
    button.clicked.connect(callback)
    return button


def _grid_group(page, title, cells, columns=3):
    box = QGroupBox(title.replace("&", "&&"))
    grid = QGridLayout(box)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(12)
    for index, cell in enumerate(cells):
        grid.addWidget(cell, index // columns, index % columns, 1, columns if cell.property("spanFullWidth") else 1)
    page.responsive_grids.append((grid, cells, columns))
    return box


def _form(page, fields, choices):
    widget = QWidget()
    outer = QVBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(_caption("Enter the available details. Blank fields can be completed on the printed form."))
    scroll, layout = _scroll_body()
    cells = {}
    for key, label, kind in fields:
        if kind in choices:
            edit = QComboBox()
            edit.addItem("Select…", "")
            for value in choices[kind]:
                edit.addItem(value, value)
            edit.currentIndexChanged.connect(page._form_changed)
        else:
            edit = QLineEdit()
            edit.setPlaceholderText("Optional")
            edit.textChanged.connect(page._form_changed)
        page.fields[key] = edit
        cells[key] = _cell(label, edit)
    software = QLineEdit()
    software.setReadOnly(True)
    software.setPlaceholderText("From connected device")
    page.fields["software_version"] = software
    cells["software_version"] = _cell("Software version · Auto", software)
    groups = (
        ("Product identification", ("product_type", "panel_sn", "cubicle_sn", "relay_sn", "socket_sn", "transformer_sn", "software_version")),
        ("Assembly & power", ("appearance", "cable_bundling", "battery_kind", "mfg_date", "main_socket", "power_socket")),
        ("Modem", ("modem_type", "modem_data_port", "modem_id", "modem_sn")),
    )
    for title, keys in groups:
        layout.addWidget(_grid_group(page, title, [cells[key] for key in keys], 2 if title == "Modem" else 3))
    layout.addStretch()
    outer.addWidget(scroll, 1)
    footer = QHBoxLayout()
    footer.addWidget(_button("←  Setup", lambda: page._show_step(0)))
    page.form_completeness = _caption("0 fields entered")
    footer.addWidget(page.form_completeness, 1)
    footer.addWidget(_button("Continue to test  →", lambda: page._show_step(2), True))
    outer.addLayout(footer)
    return widget


def _test(page, sections):
    widget = QWidget()
    outer = QVBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    counts = QHBoxLayout()
    page.test_status = _caption("0 fields recorded")
    page.section_status = _caption("0 sections")
    counts.addWidget(page.test_status)
    counts.addWidget(page.section_status)
    counts.addStretch()
    refresh = _button("Read DUT measurements", page.refresh_requested.emit)
    counts.addWidget(refresh)
    outer.addLayout(counts)
    page.lot_result_status = _caption("")
    outer.addWidget(page.lot_result_status)
    body = QHBoxLayout()
    nav_box = QGroupBox("Test sections")
    nav_box.setFixedWidth(195)
    nav = QVBoxLayout(nav_box)
    page.section_list = QListWidget()
    page.section_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    for index, section in enumerate(sections, 1):
        item = QListWidgetItem(f"{index:02d}  {SECTION_NAMES[section.key]}")
        item.setSizeHint(QSize(0, 34))
        page.section_list.addItem(item)
    page.section_list.currentRowChanged.connect(page._show_section)
    nav.addWidget(page.section_list)
    body.addWidget(nav_box)
    content = QVBoxLayout()
    head = QHBoxLayout()
    page.section_title = _caption("", "testerSectionTitle")
    page.section_progress = _caption("")
    head.addWidget(page.section_title, 1)
    head.addWidget(page.section_progress)
    content.addLayout(head)
    page.test_table = QTableWidget(0, 4)
    page.test_table.setHorizontalHeaderLabels(("Parameter", "Value / observation", "Source", "Result"))
    page.test_table.verticalHeader().hide()
    page.test_table.verticalHeader().setDefaultSectionSize(44)
    page.test_table.setAlternatingRowColors(True)
    page.test_table.setShowGrid(False)
    page.test_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    page.test_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    header = page.test_table.horizontalHeader()
    header.setMinimumSectionSize(65)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for col, width in ((1, 170), (2, 100), (3, 95)):
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        page.test_table.setColumnWidth(col, width)
    content.addWidget(page.test_table, 1)
    content.addWidget(_caption("Values arrive automatically when available. Manual entries can also be completed on the printed form. Hover over a source or result to see its rules."))
    footer = QHBoxLayout()
    page.previous_button = _button("← Previous", page._previous_section)
    page.next_button = _button("Next section →", page._next_section, True)
    footer.addWidget(page.previous_button)
    footer.addStretch()
    footer.addWidget(page.next_button)
    content.addLayout(footer)
    body.addLayout(content, 1)
    outer.addLayout(body, 1)

    # Keep the complete diagnostic view available without a second results sidebar.
    details = QWidget()
    details_layout = QVBoxLayout(details)
    details_layout.setContentsMargins(0, 0, 0, 0)
    page.lot_result_table = QTableWidget(0, 3)
    page.lot_result_table.setHorizontalHeaderLabels(("Test / measurement", "Value", "Verdict"))
    page.lot_result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    page.lot_result_table.verticalHeader().hide()
    page.lot_result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    page.lot_result_table.setMaximumHeight(150)
    details_layout.addWidget(page.lot_result_table)
    toggle = _button("All measurements && test results", lambda checked: details.setVisible(checked))
    toggle.setCheckable(True)
    outer.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
    outer.addWidget(details)
    details.hide()
    return widget


def _report(page):
    widget = QWidget()
    outer = QVBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll, layout = _scroll_body()
    box = QGroupBox("Inspection report")
    report = QVBoxLayout(box)
    report.setSpacing(12)
    page.report_summary = _caption("Ready to generate the checklist.")
    report.addWidget(page.report_summary)
    row = QHBoxLayout()
    page.form_combo = QComboBox()
    page.form_combo.addItem("Sectionalizer / S", "s")
    page.form_combo.addItem("Auto Recloser / A", "a")
    row.addWidget(_cell("Form template", page.form_combo), 1)
    page.generate_button = _button("Generate PDF", page._generate_form, True)
    row.addWidget(page.generate_button, 0, Qt.AlignmentFlag.AlignBottom)
    report.addLayout(row)
    page.report_file_label = _caption("No PDF generated for this session.")
    page.report_file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    report.addWidget(page.report_file_label)
    actions = QHBoxLayout()
    page.open_button = _button("Open PDF", page._open_pdf)
    page.print_button = _button("Print checklist", page._print_pdf)
    actions.addWidget(page.open_button)
    actions.addWidget(page.print_button)
    actions.addStretch()
    page.json_button = _button("Session JSON", page._write_session_json)
    actions.addWidget(page.json_button)
    report.addLayout(actions)
    layout.addWidget(box)
    cells = []
    for key, label in (("approved_by", "Approved by"), ("signature", "Signature / name"), ("note", "Note")):
        edit = QLineEdit()
        edit.setPlaceholderText("Optional · may be completed on paper")
        edit.textChanged.connect(page._form_changed)
        page.fields[key] = edit
        cell = _cell(label, edit)
        if key == "note":
            cell.setProperty("spanFullWidth", True)
        cells.append(cell)
    layout.addWidget(_grid_group(page, "Approval & notes", cells, 2))
    layout.addWidget(_caption("Blank manual fields stay blank for handwritten completion. Values and acceptance criteria are saved with the session."))
    layout.addStretch()
    outer.addWidget(scroll, 1)
    outer.addWidget(_button("← Back to test", lambda: page._show_step(2)), 0, Qt.AlignmentFlag.AlignLeft)
    return widget


def build_tester_ui(page, form_fields, sections, choices):
    page.setStyleSheet(STYLE)
    page.responsive_grids = []
    root = QVBoxLayout(page)
    root.setContentsMargins(10, 8, 10, 8)
    root.setSpacing(9)
    header = QFrame()
    header.setObjectName("testerHeader")
    row = QHBoxLayout(header)
    row.addWidget(_caption("FC22 Tester", "testerTitle"))
    page.session_label = _caption("Final inspection · saved automatically")
    page.session_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    row.addWidget(page.session_label, 1)
    root.addWidget(header)
    steps = QHBoxLayout()
    page.step_buttons = []
    for index, title in enumerate(("Setup", "Form data", "Run test", "Report")):
        button = _button(f"{index + 1}   {title}", lambda _checked=False, i=index: page._show_step(i))
        button.setObjectName("testerStep")
        button.setCheckable(True)
        page.step_buttons.append(button)
        steps.addWidget(button, 1)
    root.addLayout(steps)
    page.step_pages = [page._build_setup_page(), _form(page, form_fields, choices),
                       _test(page, sections), _report(page)]
    for widget in page.step_pages:
        root.addWidget(widget, 1)


