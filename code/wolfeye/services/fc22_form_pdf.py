"""Company Final Inspection Form PDF filling for the FC22 Tester.

Ported unchanged (coordinate tables and drawing behavior) from the validated
prototype ``FC22_TESTER_FORM_DRIVEN_MANUAL_DRAFT_V4/form_generator/
fc22_form_generator.py`` so the printed company layout is preserved exactly.

``fill_form`` fills either supplied company template:

    s  -> Sectionalizer  (form_generator/s.pdf)
    a  -> Auto Recloser  (form_generator/a.pdf)

The integrated WolfEye UI never calls ``build_demo_data``; it always passes
the values actually entered during the session plus the identity read from
the DUT over LAN.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pymupdf as fitz

HERE = Path(__file__).resolve().parent
PAGE_SIZE = (792, 612)
FONT = "cour"
TEXT_MARGIN = 2.0
FIT_SAFETY = 0.97

COLORS = {
    "valid": (0.0, 0.30, 0.80),
    "fail": (0.85, 0.05, 0.05),
    "critical": (1.0, 0.45, 0.0),
}

TEMPLATE_CANDIDATES = {
    "s": ("s.pdf", "s(2).pdf"),
    "a": ("a.pdf", "a(2).pdf"),
}

FIXED_COMMON = {
    "test_date": "2026-09-17",
    "panel_sn": "PNL-0001",
    "cubicle_sn": "CUB-0001",
    "relay_sn": "RLY-0001",
    "software_version": "V1.0.0",
    "socket_sn": "SOC-0001",
    "transformer_sn": "TR-0001",
    "cable_bundling": "OK",
    "mfg_date": "2026-08",
}

FIXED_BY_FORM = {
    "s": {"appearance_accepted": True, "battery_vrla": True},
    "a": {"appearance_accepted": True, "battery_vrla": True},
}

TEXT_FIELDS = {
    "test_date": (66, 177.0, 145.0, 6.4),
    "panel_sn": (153, 199.0, 246.0, 6.4),
    "software_version": (153, 209.0, 246.0, 6.4),
    "cubicle_sn": (328, 199.0, 395.0, 6.4),
    "socket_sn": (328, 209.0, 395.0, 6.4),
    "transformer_sn": (328, 219.0, 395.0, 6.4),
    "mfg_date": (319, 229.0, 394.0, 6.2),
    "main_socket": (520, 229.0, 620.0, 6.0),
    "power_socket": (678, 229.0, 764.0, 6.0),
    "relay_sn": (473, 199.0, 548.0, 6.4),
    "cable_bundling": (626, 199.0, 764.0, 6.4),
    "va": (265, 259.0, 323.0, 6.1),
    "vb": (342, 259.0, 395.0, 6.1),
    "vc": (414, 259.0, 467.0, 6.1),
    "vr": (486, 259.0, 548.0, 6.1),
    "vs": (567, 259.0, 620.0, 6.1),
    "vt": (639, 259.0, 764.0, 6.1),
    "vab": (270, 269.0, 323.0, 6.1),
    "vbc": (346, 269.0, 395.0, 6.1),
    "vac": (419, 269.0, 467.0, 6.1),
    "vtr": (491, 269.0, 548.0, 6.1),
    "vst": (571, 269.0, 620.0, 6.1),
    "vrs": (643, 269.0, 764.0, 6.1),
    "ia": (265, 283.0, 323.0, 6.1),
    "ib": (342, 283.0, 395.0, 6.1),
    "ic": (414, 283.0, 467.0, 6.1),
    "in": (486, 283.0, 548.0, 6.1),
    "p_active": (295, 297.0, 394.0, 6.0),
    "q_reactive": (453, 297.0, 548.0, 6.0),
    "s_apparent": (605, 297.0, 764.0, 6.0),
    "freq_source": (282, 307.0, 467.0, 6.0),
    "freq_load": (494, 307.0, 764.0, 6.0),
    "power_factor": (250, 317.0, 764.0, 6.0),
    "do_trip": (265, 347.0, 323.0, 6.0),
    "do_close": (265, 357.0, 323.0, 6.0),
    "do_battery": (265, 367.0, 323.0, 6.0),
    "do_heater": (265, 378.0, 323.0, 6.0),
    "di_open": (435, 347.0, 548.0, 6.0),
    "di_close": (435, 357.0, 548.0, 6.0),
    "di_lock": (435, 367.0, 548.0, 6.0),
    "di_gas": (435, 378.0, 548.0, 6.0),
    "modem_status": (710, 347.0, 764.0, 6.0),
    "sim_card": (710, 357.0, 764.0, 6.0),
    "ip_acquisition": (710, 367.0, 764.0, 6.0),
    "remote_ip": (710, 378.0, 764.0, 6.0),
    "fault_phase_phase": (265, 388.0, 323.0, 6.0),
    "fault_phase_ground": (265, 398.0, 323.0, 6.0),
    "fault_phase_sync": (265, 408.0, 323.0, 6.0),
    "charging_voltage": (405, 398.0, 548.0, 6.0),
    "charging_current": (405, 408.0, 548.0, 6.0),
    "capacitor_series": (157, 429.0, 246.0, 6.0),
    "capacitance": (333, 429.0, 395.0, 6.0),
    "voltage_rating": (477, 429.0, 548.0, 6.0),
    "temperature": (630, 429.0, 764.0, 6.0),
    "booster_output_voltage": (157, 439.0, 246.0, 6.0),
    "reclose_4_shot": (333, 439.0, 395.0, 6.0),
    "dcd": (477, 439.0, 548.0, 6.0),
    "reset_mode": (630, 439.0, 764.0, 6.0),
    "trip_close_voltage": (157, 449.0, 246.0, 6.0),
    "aux_igbt_version": (333, 449.0, 395.0, 6.0),
    "inner_lamp": (157, 469.0, 246.0, 6.0),
    "live_line": (333, 469.0, 395.0, 6.0),
    "dead_line": (477, 469.0, 548.0, 6.0),
    "led_indicators": (630, 469.0, 764.0, 6.0),
    "modem_id": (488, 218.0, 588.0, 6.0),
    "modem_sn": (640, 218.0, 764.0, 6.0),
    "approved_by": (70, 489.0, 320.0, 6.0),
    "signature": (70, 530.0, 320.0, 6.0),
    "note": (410, 523.0, 760.0, 6.0),
}

CHECK_FIELDS = {
    "appearance_accepted": (79.6, 215.5),
    "battery_vrla": (98.4, 225.0),
    "ac_available": (153.8, 322.0),
    "door_true": (153.8, 332.0),
    "lockout_true": (401.6, 332.0),
    "external_modem": (623.3, 393.5),
    "modem_c3243": (473.7, 204.0),
    "modem_uhf": (560.0, 204.0),
}

SELECTION_GROUPS = {
    "product_type": {
        "LCU": (355.0, 184.2),
        "Pole-mounted RTU": (401.0, 184.2),
        "Pad-Mounted RTU": (486.5, 184.2),
        "Recloser Control": (575.9, 184.2),
        "Disjoncteur control": (660.5, 184.2),
    },
    "appearance": {
        "Accepted": (79.6, 215.5),
        "Rejected": (131.8, 215.5),
    },
    "battery_kind": {
        "VRLA": (98.4, 225.0),
        "LFP": (138.9, 225.0),
    },
    "modem_type": {
        "C3243": (473.7, 204.0),
        "PR300-4G": (510.0, 204.0),
        "UHF": (559.4, 204.0),
        "M104": (584.8, 204.0),
        "Internal": (619.4, 204.0),
        "Others": (694.7, 204.0),
    },
}


BOOLEAN_SELECTION_GROUPS = {
    "ac_available": {
        True: (153.8, 322.0),
        False: (289.6, 322.0),
    },
    "door_true": {
        True: (153.8, 332.0),
        False: (272.4, 332.0),
    },
    "lockout_true": {
        True: (401.6, 332.0),
        False: (498.6, 332.0),
    },
}

SINGLE_BOOLEAN_FIELDS = {
    "external_modem": (623.3, 393.5),
}

PRECHECKED_BY_FORM = {
    "s": set(),
    "a": {"ac_available", "door_true", "lockout_true"},
}

ERASE_FIELDS = {
    "s": [
        (("capacitor_series",), (194.5, 419.5, 203.0, 430.8)),
        (("capacitance",), (356.7, 419.5, 365.3, 430.8)),
        (("voltage_rating",), (505.4, 419.5, 514.0, 430.8)),
        (("temperature",), (690.2, 419.0, 698.8, 430.4)),
        (("booster_output_voltage",), (194.5, 430.3, 203.0, 441.6)),
        (("reclose_4_shot",), (356.7, 430.3, 365.3, 441.6)),
        (("dcd",), (505.4, 430.3, 514.0, 441.6)),
        (("reset_mode",), (690.2, 429.8, 698.8, 441.2)),
        (("trip_close_voltage",), (194.5, 440.3, 203.0, 451.6)),
        (("aux_igbt_version",), (356.7, 440.3, 365.3, 451.6)),
    ],
    "a": [
        (("modem_status", "sim_card", "ip_acquisition", "remote_ip"), (695, 339, 765, 378)),
    ],
}


def default_template_dir() -> Path:
    """Locate the company form templates.

    Frozen builds unpack ``code/assets`` into ``sys._MEIPASS``; from source the
    templates live in ``code/assets/forms``. A fallback keeps CLI users working
    with an explicit copy of the prototype folder.
    """
    if getattr(__import__("sys"), "frozen", False):
        root = Path(__import__("sys")._MEIPASS)  # noqa: SLF001 - PyInstaller contract
        return root / "assets" / "forms"
    return Path(__file__).resolve().parents[2] / "assets" / "forms"


def _template_path(form: str, explicit: Path | None) -> Path:
    if explicit:
        path = explicit.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Template not found: {path}")
        return path

    here = HERE
    for name in TEMPLATE_CANDIDATES[form]:
        path = here / name
        if path.is_file():
            return path

    assets = default_template_dir()
    for name in TEMPLATE_CANDIDATES[form]:
        path = assets / name
        if path.is_file():
            return path

    names = ", ".join(TEMPLATE_CANDIDATES[form])
    raise FileNotFoundError(
        f"Template not found beside script or in {assets}: {names}"
    )


def _num(rng: random.Random, low: float, high: float, digits: int = 2) -> str:
    return f"{rng.uniform(low, high):.{digits}f}"


def build_demo_data(form: str, rng: random.Random) -> dict[str, object]:
    """Demo values for CLI checks only. The integrated UI never uses this."""
    data: dict[str, object] = {**FIXED_COMMON, **FIXED_BY_FORM[form]}

    data.update({key: _num(rng, 10.60, 11.40) for key in ("va", "vb", "vc", "vr", "vs", "vt")})
    data.update({key: _num(rng, 19.20, 20.80) for key in ("vab", "vbc", "vac", "vtr", "vst", "vrs")})
    data.update({key: _num(rng, 95.0, 115.0, 1) for key in ("ia", "ib", "ic")})
    data.update({
        "in": _num(rng, 0.20, 3.00, 1),
        "freq_source": _num(rng, 49.90, 50.10),
        "freq_load": _num(rng, 49.90, 50.10),
        "ac_available": True,
        "door_true": True,
        "lockout_true": True,
        "do_trip": "PASS",
        "do_close": "PASS",
        "do_battery": "PASS",
        "do_heater": "PASS",
        "di_open": "PASS",
        "di_close": "PASS",
        "di_lock": "PASS",
        "di_gas": "PASS",
        "fault_phase_phase": "PASS",
        "fault_phase_ground": "PASS",
        "fault_phase_sync": "PASS",
        "charging_voltage": "26.2 V",
        "charging_current": "0.84 A",
        "capacitor_series": "PASS",
        "capacitance": "470 uF",
        "voltage_rating": "450 V",
        "temperature": "25 C",
        "booster_output_voltage": "24.1 V",
        "reclose_4_shot": "PASS",
        "dcd": "PASS",
        "reset_mode": "PASS",
        "trip_close_voltage": "24.0 V",
        "aux_igbt_version": "V1.0",
        "inner_lamp": "PASS",
        "live_line": "PASS",
        "dead_line": "PASS",
        "led_indicators": "PASS",
        "modem_id": "MDM-01",
        "modem_sn": "MDM-0001",
        "external_modem": True,
        "modem_c3243": form == "s",
        "modem_uhf": form == "a",
        "approved_by": "TEST USER",
        "signature": "TEST SIGNATURE",
        "note": "DEMO OUTPUT - NOT FOR QC",
    })

    apparent = rng.uniform(20.0, 28.0)
    power_factor = rng.uniform(0.985, 0.997)
    active = apparent * power_factor
    reactive = math.sqrt(max(0.0, apparent**2 - active**2))

    data.update({
        "p_active": f"{active:.2f}",
        "q_reactive": f"{reactive:.2f}",
        "s_apparent": f"{apparent:.2f}",
        "power_factor": f"{power_factor * 100:.1f}%",
    })

    data.update({
        "modem_status": "PASS",
        "sim_card": "PASS",
        "ip_acquisition": "PASS",
        "remote_ip": "PASS",
    })
    return data


def _clear_template_values(page: fitz.Page, form: str, data: dict[str, object]) -> None:
    # The company templates contain a few pre-printed dashes/values. Remove
    # only their text glyphs and preserve the table line-art underneath.
    present = {key for key, value in data.items() if value not in (None, "")}
    redacted = False
    for keys, rect in ERASE_FIELDS[form]:
        if present.intersection(keys):
            page.add_redact_annot(fitz.Rect(rect), fill=None)
            redacted = True
    if redacted:
        page.apply_redactions(images=0, graphics=0, text=0)


def _fit_font_size(text: str, preferred: float, width: float) -> float:
    text_width = fitz.get_text_length(text, fontname=FONT, fontsize=preferred)
    if text_width <= width:
        return preferred
    return preferred * width / text_width * FIT_SAFETY


def _field_color(value: object) -> tuple[float, float, float]:
    status = str(value).strip().upper()
    if status in {"FAIL", "FAILED", "INVALID"}:
        return COLORS["fail"]
    if status in {"CRITICAL", "CRIT"}:
        return COLORS["critical"]
    return COLORS["valid"]


def _insert_field(page: fitz.Page, text: str, spec: tuple[float, float, float, float], color: tuple[float, float, float]) -> None:
    x, y, right, preferred = spec
    width = max(1.0, right - x - TEXT_MARGIN)
    size = _fit_font_size(text, preferred, width)
    page.insert_text(
        fitz.Point(x, y),
        text,
        fontsize=size,
        fontname=FONT,
        color=color,
        overlay=True,
    )


def _draw_x(page: fitz.Page, x: float, y: float, size: float = 4.4) -> None:
    half = size / 2
    page.draw_line(
        fitz.Point(x - half, y - half),
        fitz.Point(x + half, y + half),
        color=COLORS["valid"],
        width=0.65,
        overlay=True,
    )
    page.draw_line(
        fitz.Point(x - half, y + half),
        fitz.Point(x + half, y - half),
        color=COLORS["valid"],
        width=0.65,
        overlay=True,
    )


def _draw_checkbox(page: fitz.Page, x: float, y: float, checked: bool) -> None:
    half = 3.0
    # Erase the template glyph only, preserving its label text.
    page.draw_rect(
        fitz.Rect(x - half - 0.7, y - half - 0.7, x + half + 0.7, y + half + 0.7),
        color=None, fill=(1, 1, 1), overlay=True,
    )
    page.draw_rect(
        fitz.Rect(x - half, y - half, x + half, y + half),
        color=(0, 0, 0), width=0.55, overlay=True,
    )
    if checked:
        _draw_x(page, x, y, size=4.6)


def _draw_selection_groups(page: fitz.Page, values: dict[str, object]) -> None:
    for field, choices in SELECTION_GROUPS.items():
        selected = str(values.get(field, "")).strip()
        if not selected:
            continue
        # UI uses '-' for not applicable. Clear the group without checking any option.
        for label, (x, y) in choices.items():
            _draw_checkbox(page, x, y, selected == label)

    # These rows have a True and False checkbox. Redraw both boxes so a
    # pre-checked template can also be changed explicitly by the operator.
    for field, choices in BOOLEAN_SELECTION_GROUPS.items():
        if field not in values or values[field] is None or values[field] == "":
            continue
        selected = values[field]
        for option, (x, y) in choices.items():
            _draw_checkbox(page, x, y, selected is option)

    # External Modem is a single checkbox. False explicitly clears it.
    for field, (x, y) in SINGLE_BOOLEAN_FIELDS.items():
        if field not in values or values[field] in (None, ""):
            continue
        value = values[field]
        _draw_checkbox(page, x, y, value is True)


def fill_form(
    form: str,
    output: Path,
    seed: int | None = None,
    template_path: Path | None = None,
    data: dict[str, object] | None = None,
) -> Path:
    if form not in TEMPLATE_CANDIDATES:
        raise ValueError(f"Unsupported form type: {form}")
    values = dict(data) if data is not None else build_demo_data(form, random.Random(seed))
    template = _template_path(form, template_path)

    with fitz.open(template) as doc:
        if len(doc) != 1:
            raise ValueError("Expected a one-page checklist template")

        page = doc[0]
        size = (round(page.rect.width), round(page.rect.height))
        if size != PAGE_SIZE:
            raise ValueError(f"Unexpected template size: {size[0]}x{size[1]}")

        _clear_template_values(page, form, values)

        for key, spec in TEXT_FIELDS.items():
            value = values.get(key)
            if value not in (None, ""):
                _insert_field(page, str(value), spec, _field_color(value))

        prechecked = PRECHECKED_BY_FORM[form]
        skip_checkbox_keys = set(BOOLEAN_SELECTION_GROUPS) | set(SINGLE_BOOLEAN_FIELDS)
        for key, (x, y) in CHECK_FIELDS.items():
            if key in skip_checkbox_keys:
                continue
            if values.get(key) is True and key not in prechecked:
                _draw_x(page, x, y)

        _draw_selection_groups(page, values)

        output.parent.mkdir(parents=True, exist_ok=True)
        doc.save(output, garbage=3, deflate=True)

    return output
