"""Corporate PDF reports for EmWolf scenario runs."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from wolfeye.branding import PRODUCT_NAME
from wolfeye.services.emwolf_protocol import BOARD_SAMPLE_TIME_US, CHANNEL_NAMES, Project


BRAND_NAVY = colors.HexColor("#16324A")
BRAND_BLUE = colors.HexColor("#087AD1")
BRAND_CYAN = colors.HexColor("#00A8E8")
BRAND_LIGHT = colors.HexColor("#EAF3F8")
INK = colors.HexColor("#243746")
MUTED = colors.HexColor("#667784")
GRID = colors.HexColor("#CAD6DE")
SUCCESS = colors.HexColor("#087A20")
DANGER = colors.HexColor("#B42318")
SOFT_GREEN = colors.HexColor("#E7F5EA")
SOFT_RED = colors.HexColor("#FDECEC")
SOFT_GRAY = colors.HexColor("#F4F6F8")


@dataclass(frozen=True)
class DITransition:
    input_id: int
    value: bool
    elapsed_us: int


@dataclass
class ScenarioExecution:
    state: str
    transitions: list[DITransition] = field(default_factory=list)
    trip_time_us: int | None = None
    trip_input: int | None = None
    trip_value: bool | None = None
    operation: str | None = None
    output_applied_us: int | None = None
    ended_us: int | None = None


@dataclass
class EmWolfRunReport:
    """Snapshot of one transmitted project and its board-timestamped results."""

    project: Project
    started_at: datetime
    executions: list[ScenarioExecution]
    completed_at: datetime | None = None
    board_run_id: str | None = None
    board_state: str = ""
    results_received: bool = False
    _trip_scenario_indices: list[int] = field(default_factory=list, repr=False)
    _next_trip_position: int = field(default=0, repr=False)
    _open_seen: bool = field(default=False, repr=False)

    @classmethod
    def begin(cls, project: Project, *, started_at: datetime | None = None) -> EmWolfRunReport:
        snapshot = copy.deepcopy(project)
        snapshot.validate()
        trip_indices = [
            index
            for index, scenario in enumerate(snapshot.scenarios)
            if scenario.end_type == "DI_TOGGLE"
        ]
        executions = [
            ScenarioExecution(
                "ARMED" if index in trip_indices else "CONFIGURED"
            )
            for index in range(len(snapshot.scenarios))
        ]
        return cls(
            project=snapshot,
            started_at=started_at or datetime.now().astimezone(),
            executions=executions,
            _trip_scenario_indices=trip_indices,
        )

    @property
    def receipt_description(self) -> str:
        if not self.board_run_id:
            return "Configuration only - no measured board results"
        if self.results_received:
            return "All recorded results received; run status is shown separately"
        return "Partial results snapshot - the run or result transfer is not complete"

    @property
    def current_trip_scenario_index(self) -> int | None:
        if self._next_trip_position >= len(self._trip_scenario_indices):
            return None
        return self._trip_scenario_indices[self._next_trip_position]

    def record_board_event(self, event: dict) -> int | None:
        """Use the board's stage ID and full timestamp, including offline replay."""
        index=int(event["scenario"])
        if not 0<=index<len(self.executions):
            raise ValueError("Board event refers to an unknown scenario")
        execution=self.executions[index]
        kind=event["kind"]
        if kind==1:
            if execution.state in ("ARMED","CONFIGURED"): execution.state="RUNNING"
        elif kind==2:
            execution.output_applied_us=event["time_us"]
        elif kind==3:
            if event["input_id"]==self.project.scenarios[index].digital_input:
                execution.transitions.append(DITransition(event["input_id"],event["value"],event["time_us"]))
        elif kind==4:
            if index not in self._trip_scenario_indices:
                raise ValueError("Trip result does not match a DI scenario")
            self._next_trip_position=self._trip_scenario_indices.index(index)
            result=self.record_trip(event["input_id"],event["value"],event["time_us"])
            if self.board_run_id and self.board_state!="COMPLETED": self.completed_at=None
            return result
        elif kind==5:
            execution.ended_us=event["time_us"]
            if execution.state not in ("TRIPPED","RECLOSED","CLOSED"):
                execution.state="COMPLETED"
        return None

    def record_transition(self, input_id: int, value: bool, elapsed_us: int) -> int | None:
        index = self.current_trip_scenario_index
        if index is None:
            return None
        scenario = self.project.scenarios[index]
        if input_id != scenario.digital_input:
            return None
        transition = DITransition(input_id, value, elapsed_us)
        execution = self.executions[index]
        if execution.transitions:
            return None
        execution.transitions.append(transition)
        return index

    def record_trip(self, input_id: int, value: bool, elapsed_us: int) -> int | None:
        index = self.current_trip_scenario_index
        if index is None:
            return None
        scenario = self.project.scenarios[index]
        if input_id != scenario.digital_input:
            return None
        execution = self.executions[index]
        input_name = self.project.setup.digital_input_name(input_id).casefold()
        model = self.project.device.model.strip().upper()
        is_auto_recloser = model == "FC22AR"
        if model == "FC22AR":
            is_open, is_close = input_id == 1, input_id == 2
        elif model == "FC22S":
            is_open, is_close = input_id == 2, input_id == 1
        else:
            is_open = "open" in input_name or "trip" in input_name
            is_close = "close" in input_name
        if is_open:
            execution.operation = "TRIP"
            execution.state = "TRIPPED"
            self._open_seen = True
        elif is_close:
            if is_auto_recloser and self._open_seen:
                execution.operation = "RECLOSE"
                execution.state = "RECLOSED"
            else:
                execution.operation = "CLOSE"
                execution.state = "CLOSED"
            self._open_seen = False
        else:
            execution.operation = "DI TOGGLE"
            execution.state = "COMPLETED"
        execution.trip_time_us = elapsed_us
        execution.trip_input = input_id
        execution.trip_value = value
        self._next_trip_position += 1
        if self._next_trip_position >= len(self._trip_scenario_indices):
            self.completed_at = datetime.now().astimezone()
        return index


def _format_number(value: float) -> str:
    return f"{value:g}"


def _end_condition(scenario, setup) -> str:
    if scenario.end_type == "DI_TOGGLE":
        input_name = setup.digital_input_name(scenario.digital_input)
        return f"{input_name} (DI{scenario.digital_input}) - toggle"
    if scenario.end_type == "TIME":
        return f"Time - {_format_number(scenario.end_value)} s"
    if scenario.end_type == "CYCLES":
        return f"Cycles - {_format_number(scenario.end_value)}"
    return "Infinite"


def _scenario_type(scenario) -> str:
    return {
        "DI_TOGGLE": "DI TOGGLE",
        "TIME": "TIME",
        "CYCLES": "CYCLES",
        "INFINITE": "INFINITE",
    }.get(scenario.end_type, scenario.end_type.replace("_", " "))


def _table(data, widths, *, header=True, alignments=None) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.45, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 7.2),
            ]
        )
        first_data_row = 1
    else:
        first_data_row = 0
    for row in range(first_data_row, len(data)):
        if (row - first_data_row) % 2:
            style.append(("BACKGROUND", (0, row), (-1, row), SOFT_GRAY))
    if alignments:
        for column, alignment in enumerate(alignments):
            style.append(("ALIGN", (column, 0), (column, -1), alignment))
    table.setStyle(TableStyle(style))
    return table


def _draw_page(canvas, document) -> None:
    canvas.saveState()
    width, _height = landscape(A4)
    canvas.setStrokeColor(BRAND_CYAN)
    canvas.setLineWidth(1.2)
    canvas.line(14 * mm, 12 * mm, width - 14 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        14 * mm, 7.5 * mm, f"{PRODUCT_NAME} / EmWolf - Trip / Reclose Time Report"
    )
    canvas.drawRightString(width - 14 * mm, 7.5 * mm, f"Page {document.page}")
    canvas.restoreState()


def _logo(path: Path, width: float, height: float):
    if not path.is_file():
        return Spacer(width, height)
    image = Image(str(path), width=width, height=height, kind="proportional")
    image.hAlign = "LEFT"
    return image


def generate_emwolf_pdf(
    output_path: Path,
    report: EmWolfRunReport,
    *,
    assets_dir: Path | None = None,
) -> None:
    """Create a formal A4 report with up to four vertical stage cards per page."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir = assets_dir or Path(__file__).resolve().parents[2] / "assets"
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=20,
        textColor=BRAND_NAVY,
        alignment=TA_LEFT,
    )
    stage_style = ParagraphStyle(
        "Stage",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    scenario_style = ParagraphStyle(
        "ScenarioName",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=BRAND_NAVY,
        alignment=TA_CENTER,
    )
    trip_label_style = ParagraphStyle(
        "TripLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=MUTED,
        alignment=TA_CENTER,
    )
    trip_value_style = ParagraphStyle(
        "TripValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=SUCCESS,
        alignment=TA_CENTER,
    )
    close_value_style = ParagraphStyle(
        "CloseValue",
        parent=trip_value_style,
        textColor=DANGER,
    )
    trip_empty_style = ParagraphStyle(
        "TripEmpty",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=MUTED,
        alignment=TA_CENTER,
    )
    detail_label_style = ParagraphStyle(
        "DetailLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6.5,
        leading=8,
        textColor=MUTED,
        alignment=TA_CENTER,
    )
    detail_value_style = ParagraphStyle(
        "DetailValue",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.2,
        leading=9,
        textColor=INK,
        alignment=TA_CENTER,
    )
    tiny_label_style = ParagraphStyle(
        "TinyLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=5.4,
        leading=6.2,
        textColor=INK,
        alignment=TA_CENTER,
    )
    tiny_header_style = ParagraphStyle(
        "TinyHeader",
        parent=tiny_label_style,
        fontSize=5.1,
        leading=5.8,
        textColor=colors.white,
    )
    tiny_value_style = ParagraphStyle(
        "TinyValue",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=5.3,
        leading=6.1,
        textColor=INK,
        alignment=TA_CENTER,
    )
    close_label_style = ParagraphStyle(
        "CloseLabel",
        parent=tiny_label_style,
        textColor=DANGER,
    )
    output_trip_label_style = ParagraphStyle(
        "TripOutputLabel",
        parent=tiny_label_style,
        textColor=SUCCESS,
    )

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=16 * mm,
        title=f"{PRODUCT_NAME} EmWolf Trip / Reclose Time Report",
        author=PRODUCT_NAME,
        subject="EmWolf DI trip and reclose times",
    )
    usable_width = landscape(A4)[0] - document.leftMargin - document.rightMargin
    story = []
    report_id = f"EW-{report.started_at:%Y%m%d-%H%M%S}"
    scenarios = list(zip(report.project.scenarios, report.executions))

    def report_header() -> Table:
        header = Table(
            [[
                _logo(assets_dir / "company.png", 27 * mm, 14 * mm),
                Paragraph("EMWOLF TRIP / RECLOSE TIME REPORT", title_style),
                _logo(assets_dir / "wolfeye.png", 29 * mm, 17 * mm),
            ]],
            colWidths=[33 * mm, usable_width - 68 * mm, 35 * mm],
        )
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (2, 0), (2, 0), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, 0), 2, BRAND_BLUE),
        ]))
        return header

    device = report.project.device
    device_identity = (
        f"{device.model}  |  FW {device.firmware}  |  HW {device.hardware}  |  Build {device.build}"
        if device.available
        else f"Not read from {PRODUCT_NAME} LAN"
    )
    device_link = (
        f"{device.ip or '-'}  |  {device.transport or 'Saved project'}"
        if device.available
        else "Offline / unavailable"
    )
    metadata = [
        ["REPORT ID", report_id, "TEST DATE", report.started_at.strftime("%Y-%m-%d %H:%M:%S")],
        ["DEVICE UNDER TEST", device_identity, "LAN / SOURCE", device_link],
        ["BOARD SAMPLE TIME", f"{BOARD_SAMPLE_TIME_US} us", "STAGES", str(len(scenarios))],
        ["BOARD RUN", report.board_run_id or "Not uploaded", "RUN STATE", report.board_state or "CONFIGURATION ONLY"],
        ["RESULTS", "Fully received" if report.results_received else "Partial snapshot" if report.board_run_id else "No measured results",
         "TIME BASIS", "Output LOAD to DI edge; network delay excluded"],
    ]

    def stage_card(stage_number: int, scenario, execution, card_width: float) -> Table:
        trip_input_name = (
            ""
            if execution.trip_input is None
            else report.project.setup.digital_input_name(execution.trip_input)
        )
        is_reclose = execution.operation == "RECLOSE"
        if execution.trip_time_us is None:
            trip_value = Paragraph(
                "NOT RECORDED" if scenario.end_type == "DI_TOGGLE" else "N/A",
                trip_empty_style,
            )
            trip_background = SOFT_GRAY
        else:
            trip_value = Paragraph(
                f"{execution.trip_time_us / 1000:.3f} ms"
                f"<br/><font size='8'>{execution.trip_time_us} us</font>",
                close_value_style if is_reclose else trip_value_style,
            )
            trip_background = SOFT_RED if is_reclose else SOFT_GREEN
        trip_input = (
            "-"
            if execution.trip_input is None
            else (
                f"{trip_input_name} "
                f"(DI{execution.trip_input}) / {'HIGH' if execution.trip_value else 'LOW'}"
            )
        )
        detail_width = card_width - 5 * mm
        details = Table(
            [
                [Paragraph("TYPE", detail_label_style), Paragraph(escape(_scenario_type(scenario)), detail_value_style)],
                [Paragraph("CONDITION", detail_label_style), Paragraph(escape(_end_condition(scenario, report.project.setup)), detail_value_style)],
                [Paragraph("STATUS", detail_label_style), Paragraph(escape(execution.state), detail_value_style)],
                [Paragraph("RESULT INPUT", detail_label_style), Paragraph(escape(trip_input), detail_value_style)],
            ],
            colWidths=[18 * mm, detail_width - 18 * mm],
        )
        details.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.35, GRID),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
        ]))

        analog_rows = [[
            Paragraph("CH", tiny_header_style),
            Paragraph("ON", tiny_header_style),
            Paragraph("AMP", tiny_header_style),
            Paragraph("Hz", tiny_header_style),
            Paragraph("PH", tiny_header_style),
            Paragraph("H1 O/A", tiny_header_style),
            Paragraph("H2 O/A", tiny_header_style),
        ]]
        for group_name, channel_names in (
            ("VOLTAGE", CHANNEL_NAMES[:4]),
            ("CURRENT", CHANNEL_NAMES[4:]),
        ):
            analog_rows.append([Paragraph(group_name, tiny_label_style)] + [""] * 6)
            for channel_name in channel_names:
                analog = scenario.analogs[channel_name]
                analog_rows.append([
                    Paragraph(channel_name, tiny_label_style),
                    Paragraph("ON" if analog.enabled else "OFF", tiny_value_style),
                    Paragraph(_format_number(analog.amplitude), tiny_value_style),
                    Paragraph(_format_number(analog.frequency), tiny_value_style),
                    Paragraph(str(analog.phase), tiny_value_style),
                    Paragraph(
                        f"{analog.harmonic1_order}/{_format_number(analog.harmonic1_amplitude)}",
                        tiny_value_style,
                    ),
                    Paragraph(
                        f"{analog.harmonic2_order}/{_format_number(analog.harmonic2_amplitude)}",
                        tiny_value_style,
                    ),
                ])
        analog_table = Table(
            analog_rows,
            colWidths=[
                detail_width * 0.12,
                detail_width * 0.11,
                detail_width * 0.19,
                detail_width * 0.13,
                detail_width * 0.12,
                detail_width * 0.165,
                detail_width * 0.165,
            ],
            rowHeights=[3.6 * mm] + [3.3 * mm] * 10,
        )
        analog_style = [
            ("GRID", (0, 0), (-1, -1), 0.3, GRID),
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("SPAN", (0, 1), (-1, 1)),
            ("SPAN", (0, 6), (-1, 6)),
            ("BACKGROUND", (0, 1), (-1, 1), BRAND_LIGHT),
            ("BACKGROUND", (0, 6), (-1, 6), BRAND_LIGHT),
            ("TEXTCOLOR", (0, 1), (-1, 1), BRAND_NAVY),
            ("TEXTCOLOR", (0, 6), (-1, 6), BRAND_NAVY),
        ]
        for row_index in (2, 4, 7, 9):
            analog_style.append(("BACKGROUND", (0, row_index), (-1, row_index), SOFT_GRAY))
        analog_table.setStyle(TableStyle(analog_style))

        output_labels = ("CLOSE (DO1)", "TRIP / OPEN (DO2)", "DO3", "DO4")
        output_cells = []
        for output_index, (label, enabled) in enumerate(
            zip(output_labels, scenario.digital_outputs)
        ):
            label_style = (
                close_label_style
                if output_index == 0
                else output_trip_label_style
                if output_index == 1
                else tiny_label_style
            )
            output_cells.extend([
                Paragraph(label, label_style),
                Paragraph("ON" if enabled else "OFF", tiny_label_style),
            ])
        outputs = Table(
            [
                [Paragraph("DIGITAL OUTPUTS", tiny_label_style), "", "", ""],
                output_cells[:4],
                output_cells[4:],
            ],
            colWidths=[detail_width * 0.34, detail_width * 0.16] * 2,
            rowHeights=[3.8 * mm, 4.6 * mm, 4.6 * mm],
        )
        output_style = [
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_LIGHT),
            ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_NAVY),
            ("GRID", (0, 0), (-1, -1), 0.3, GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]
        for output_index, enabled in enumerate(scenario.digital_outputs):
            row_index = 1 + output_index // 2
            column_index = 1 + (output_index % 2) * 2
            if output_index == 0:
                enabled_background, enabled_text = SOFT_RED, DANGER
            elif output_index == 1:
                enabled_background, enabled_text = SOFT_GREEN, SUCCESS
            else:
                enabled_background, enabled_text = BRAND_LIGHT, BRAND_BLUE
            output_style.extend([
                ("BACKGROUND", (column_index, row_index), (column_index, row_index), enabled_background if enabled else SOFT_GRAY),
                ("TEXTCOLOR", (column_index, row_index), (column_index, row_index), enabled_text if enabled else MUTED),
            ])
        outputs.setStyle(TableStyle(output_style))

        card = Table(
            [
                [Paragraph(f"STAGE {stage_number}", stage_style)],
                [Paragraph(escape(scenario.name), scenario_style)],
                [details],
                [Paragraph({"TRIP": "TRIP TIME", "RECLOSE": "RECLOSE TIME", "CLOSE": "CLOSE TIME"}.get(execution.operation, "RESPONSE TIME"), trip_label_style)],
                [trip_value],
                [analog_table],
                [outputs],
            ],
            colWidths=[card_width],
            rowHeights=[9 * mm, 9 * mm, 20 * mm, 5 * mm, 19 * mm, 36.6 * mm, 13 * mm],
        )
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), BRAND_NAVY),
            ("BACKGROUND", (0, 1), (0, 1), BRAND_LIGHT),
            ("BACKGROUND", (0, 4), (0, 4), trip_background),
            ("BOX", (0, 0), (-1, -1), 0.8, BRAND_BLUE),
            ("LINEBELOW", (0, 0), (0, 4), 0.45, GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("TOPPADDING", (0, 0), (0, 1), 3),
            ("BOTTOMPADDING", (0, 0), (0, 1), 3),
            ("TOPPADDING", (0, 3), (0, 3), 3),
            ("BOTTOMPADDING", (0, 3), (0, 3), 0),
            ("TOPPADDING", (0, 4), (0, 4), 2),
            ("BOTTOMPADDING", (0, 4), (0, 4), 4),
            ("TOPPADDING", (0, 2), (0, 2), 0),
            ("BOTTOMPADDING", (0, 2), (0, 2), 0),
            ("TOPPADDING", (0, 5), (0, 6), 0),
            ("BOTTOMPADDING", (0, 5), (0, 6), 0),
        ]))
        return card

    groups = [scenarios[index:index + 4] for index in range(0, len(scenarios), 4)] or [[]]
    for group_index, group in enumerate(groups):
        story.extend([report_header(), Spacer(1, 4 * mm)])
        metadata_table = _table(
            metadata,
            [34 * mm, 75 * mm, 29 * mm, usable_width - 138 * mm],
            header=False,
        )
        metadata_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (0, -1), BRAND_LIGHT),
            ("BACKGROUND", (2, 0), (2, -1), BRAND_LIGHT),
            ("TEXTCOLOR", (0, 0), (0, -1), BRAND_NAVY),
            ("TEXTCOLOR", (2, 0), (2, -1), BRAND_NAVY),
        ]))
        story.extend([metadata_table, Spacer(1, 4 * mm)])
        if group:
            slot_width = usable_width / 4
            card_width = slot_width - 4 * mm
            cards = [
                stage_card(group_index * 4 + offset + 1, scenario, execution, card_width)
                for offset, (scenario, execution) in enumerate(group)
            ]
            card_row = Table([cards], colWidths=[slot_width] * len(cards), hAlign="CENTER")
            card_row.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(card_row)
        if group_index != len(groups) - 1:
            story.append(PageBreak())

    document.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
