"""Observed checklist values from the same native snapshots as Measurements.

These are measurements, not acceptance verdicts. Digital/protection tests need
an explicit test rule; a status bit alone cannot certify a test as PASS.
"""
from __future__ import annotations

import math

from wolfeye.models import MeasurementSnapshot

MEASUREMENT_FIELDS = {
    "va": "Ua", "vb": "Ub", "vc": "Uc", "vr": "Ur", "vs": "Us", "vt": "Ut",
    "vab": "Uab", "vbc": "Ubc", "vac": "Uca", "vtr": "Utr", "vst": "Ust", "vrs": "Urs",
    "ia": "Ia", "ib": "Ib", "ic": "Ic", "in": "In",
    "p_active": "P.P Total", "q_reactive": "Q.P Total", "s_apparent": "S.P Total",
    "freq_source": "F ABC", "freq_load": "F RST", "power_factor": "Total PF",
}
STATUS_FIELDS = {"ac_available": "AC supply", "door_true": "Door open", "lockout_true": "Lockout(Any)"}


def snapshot_readings(snapshot: MeasurementSnapshot) -> dict[str, dict[str, object]]:
    readings = {}
    for channel, fields, values in (("analog", MEASUREMENT_FIELDS, snapshot.analog),
                                    ("binary", STATUS_FIELDS, snapshot.binary)):
        for field, point in fields.items():
            value = values.get(point)
            if channel == "analog":
                if type(value) not in (int, float) or not math.isfinite(value):
                    continue
            elif type(value) is not bool:
                continue
            readings[field] = {"source": f"{channel}.{point}", "value": value,
                               "timestamp": snapshot.timestamp.isoformat(), "kind": "observed",
                               "unit": "raw" if channel == "analog" else ""}
    return readings
