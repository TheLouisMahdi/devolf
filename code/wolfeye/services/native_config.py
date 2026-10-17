from __future__ import annotations

from typing import Any

from wolfeye.config_schema import AR_MODES, BAUD_RATES, TCC_TYPES
from wolfeye.numeric_schema import validate_numeric_config


_BOOL = (False, True)
_PROTECTION_MODES = ("DISABLE", "ALARM", "TRIP", "RECLOSE")
_AUTO_OPEN_MODES = ("DISABLE", "TIMER", "POWER FLOW")
_FUNCTION_TYPES = ("BINARY", "ANALOG")
_DIGITAL_OPERATORS = ("OR", "AND", "EQUAL")
_ANALOG_OPERATORS = ("GREATER", "LESS")
_FUNCTION_ACTIONS = ("NOTHING", "OPEN", "CLOSE")
_INDIVIDUAL_HARMONICS = (
    "DISABLE",
    *(f"I{order}" for order in range(2, 16)),
    *(f"IN{order}" for order in range(2, 16)),
    *(f"V{order}" for order in range(2, 16)),
)
_SERIAL_PARITY = ("NONE", "ODD", "EVEN")
_DNP_MAP_OPTIONS = (
    ("G1V1", "G1V2"),
    ("G2V1", "G2V2", "G2V3"),
    tuple(f"G30V{i}" for i in range(1, 7)),
    tuple(f"G32V{i}" for i in range(1, 9)),
    ("G3V1", "G3V2"),
    ("G4V1", "G4V2", "G4V3"),
    ("G10V1", "G10V2"),
    ("G11V1", "G11V2"),
    tuple(f"G40V{i}" for i in range(1, 5)),
    tuple(f"G42V{i}" for i in range(1, 9)),
    ("G20V1", "G20V2", "G20V5", "G20V6"),
    ("G22V1", "G22V2", "G22V5", "G22V6"),
)
_DNP_CONFIG_NAMES = (
    "static_binary_input",
    "event_binary_input",
    "static_analog_input",
    "event_analog_input",
    None,
    "event_double_binary",
    None,
    "event_binary_output",
    "static_analog_output",
    "event_analog_output",
    "static_counter",
    "event_counter",
)
_IEC_BASE_NAMES = (
    "single_status",
    "double_status",
    "measured_values",
    "integrated_total",
    "single_command",
    "double_command",
    "set_point_command",
    "parameter_command",
)
_FEATURE_INDEX = {
    "nps": 2,
    "admittance": 3,
    "over_voltage": 7,
    "over_frequency": 9,
    "harmonic": 1,
    "abr": 4,
    "alarm_mode": 5,
    "hot_line_tag": 12,
    "ll_link_to_hlt": 13,
    "uv4_sag": 6,
    "ov3": 8,
    "rocof": 10,
    "vvs": 11,
    "pdop": 19,
    "pdup": 20,
    "dft": 15,
    "ssm": 14,
    "harmonic_ir_blocking": 18,
    "logical_block_close": 21,
    "llb": 17,
    "breaker": 22,
}


def _choice(options: tuple[Any, ...], value: Any, default: Any | None = None) -> Any:
    try:
        return options[int(value)]
    except (IndexError, TypeError, ValueError):
        return options[0] if default is None else default


def _index(options: tuple[Any, ...], value: Any, default: int = 0) -> int:
    try:
        return options.index(value)
    except ValueError:
        return default


def _ms(value: Any) -> float:
    return float(value) / 1000.0


def _to_ms(value: Any) -> int:
    return round(float(value) * 1000.0)


def _ip(value: Any) -> str:
    return ".".join(str(int(part)) for part in value)


def _ip_parts(value: Any) -> list[int]:
    parts = str(value).strip().split(".")
    if len(parts) != 4:
        raise ValueError(f"Invalid IPv4 address: {value}")
    result = [int(part) for part in parts]
    if any(part < 0 or part > 255 for part in result):
        raise ValueError(f"Invalid IPv4 address: {value}")
    return result


def update_config_from_native(config: dict[str, Any], native: dict[str, Any]) -> None:
    """Populate the existing UI model from the native Configure snapshot."""
    general = config["general"]
    measurement = general["measurement"]
    system = native["sy"]
    native_measurement = system["m"]
    measurement["frequency_hz"] = _choice(("50", "60"), native_measurement["f"])
    measurement["rated_voltage_v"] = int(native_measurement["v"])
    measurement["source_side"] = _choice(("ABC", "RST"), native_measurement["ss"])
    measurement["phase_rotation"] = _choice(
        ("ABC", "ACB", "BCA", "CAB", "BAC", "CBA"), native_measurement["pc"]
    )
    coefficients = measurement["coefficients"]
    for name, value in zip(("line_a", "line_b", "line_c", "residual"), native_measurement["c"]):
        coefficients[name] = int(value)
    deadbands = measurement["deadbands"]
    raw_deadbands = native_measurement["db"]
    for name, value in zip(
        ("voltages_v", "battery_voltage_v", "phase_currents_a", "residual_currents_a",
         "power_factor_pct", "frequency_hz", "powers", "counters"),
        raw_deadbands,
    ):
        deadbands[name] = (
            float(value) / 1000.0 if name == "voltages_v"
            else float(value) / 10.0 if name in {"battery_voltage_v", "frequency_hz"}
            else int(value)
        )
    general["system"]["lsd_level"] = float(native_measurement["lsd"]) / 1000.0

    scada = general["scada"]
    native_scada = native["s"]
    scada["enabled"] = bool(native_scada["s"])
    scada["protocol"] = _choice(("DNP3", "IEC"), native_scada["p"])
    scada["data_port"] = _choice(("ETHERNET", "RS232", "RS485", "MODEM"), native_scada["d"])
    dnp = scada["dnp3"]
    link = native_scada["dn"]["l"]
    dnp["link"].update(
        slave_address=int(link["a"][0]), master_address=int(link["a"][1]),
        confirm_retry=int(link["cr"]), confirm_timeout_s=_ms(link["ct"]),
        keep_alive_s=_ms(link["k"]), confirm_user_data=bool(link["cu"]),
        keep_alive_enabled=bool(link["ke"]),
    )
    application = native_scada["dn"]["a"]
    dnp["application"].update(
        cold_restart_delay=int(application["c"]), warm_restart_delay=int(application["w"]),
        solicited_confirm_timeout_s=_ms(application["sc"]), select_timeout_s=_ms(application["st"]),
    )
    unsolicited = native_scada["dn"]["u"]
    dnp["unsolicited"].update(
        enabled=bool(unsolicited["e"]), hold_time_s=int(unsolicited["h"]),
        class_1=bool(unsolicited["u"][1]), class_2=bool(unsolicited["u"][2]),
        class_3=bool(unsolicited["u"][3]),
    )
    timesync = native_scada["dn"]["t"]
    dnp["time_sync"].update(enabled=bool(timesync["e"]), request_interval_s=_ms(timesync["r"]))
    for index, name in enumerate(_DNP_CONFIG_NAMES):
        if name:
            dnp["mapping"][name] = _choice(_DNP_MAP_OPTIONS[index], native_scada["ma"][index])
    if "i" in native_scada:
        _read_iec(scada["iec"], native_scada["i"])

    io = general["io"]
    native_io = system["io"]
    io["open_close"].update(
        open_read_mode=_choice(("SINGLE", "DOUBLE"), native_io["r"][0]),
        close_read_mode=_choice(("SINGLE", "DOUBLE"), native_io["r"][1]),
        open_need_confirm=bool(native["onc"]), close_need_confirm=bool(native["cnc"]),
    )
    ethernet = native_io["e"]
    io["ethernet"].update(
        dhcp=bool(ethernet["d"]), ip=_ip(ethernet["i"]),
        subnet_mask=_ip(ethernet["s"]), gateway=_ip(ethernet["g"]),
    )
    digital_inputs = io["digital_inputs"]
    digital_inputs.update(
        chatter_enabled=bool(native_io["i"]["c"]),
        chatter_reset_s=_ms(native_io["i"]["r"]),
        validation_time_s=_ms(native_io["i"]["v"]),
    )
    digital_inputs["inputs"] = [
        _choice(("DISABLE", "HIGH STATE", "LOW STATE"), value)
        for value in native_io["i"]["g"][:7]
    ]
    for target, source in zip(io["digital_outputs"], native_io["o"][:7]):
        target.update({
            "when": int(source["i"]),
            "is": _choice(("FALSE", "TRUE"), source["a"]),
            "recognition_s": _ms(source.get("t", 1000)),
            "then": _choice(("DISABLE", "LATCH ON", "PULSE ON"), source["s"]),
            "for_s": _ms(source["o"]),
        })
    _read_serial(scada["ports"]["rs232"], native_io["r2"])
    _read_serial(scada["ports"]["rs485"], native_io["r4"])
    tcp = native_scada["dn"]["e"]
    scada["ports"]["ethernet"].update(
        mode=_choice(("SERVER", "CLIENT"), tcp["m"]), local_port=int(tcp["l"]),
        remote_port=int(tcp["r"]), remote_ip=_ip(tcp["i"]),
    )
    modem_tcp = native_scada["dn"]["m"]
    scada["ports"]["modem"].update(
        apn=str(native_io["m"]["a"]), network=_choice(("AUTO", "GSM", "LTE"), native_io["m"]["p"]),
        baudrate=_choice(BAUD_RATES, native_io["m"]["b"]),
        mode=_choice(("SERVER", "CLIENT"), modem_tcp["m"]), local_port=int(modem_tcp["l"]),
        remote_port=int(modem_tcp["r"]), remote_ip=_ip(modem_tcp["i"]),
    )
    _read_global_system(general, native)
    _read_protection(config["protection"], native)


def update_native_from_config(native: dict[str, Any], config: dict[str, Any]) -> None:
    """Apply the existing UI model to the native Configure snapshot in place."""
    validate_numeric_config(config)
    general = config["general"]
    measurement = general["measurement"]
    system = native["sy"]
    native_measurement = system["m"]
    native_measurement.update(
        f=_index(("50", "60"), str(measurement["frequency_hz"])),
        v=int(measurement["rated_voltage_v"]),
        ss=_index(("ABC", "RST"), measurement["source_side"]),
        pc=_index(("ABC", "ACB", "BCA", "CAB", "BAC", "CBA"), measurement["phase_rotation"]),
        lsd=round(float(general["system"]["lsd_level"]) * 1000),
    )
    native_measurement["c"] = [int(measurement["coefficients"][name]) for name in ("line_a", "line_b", "line_c", "residual")]
    db = measurement["deadbands"]
    native_measurement["db"] = [
        round(float(db["voltages_v"]) * 1000), round(float(db["battery_voltage_v"]) * 10),
        int(db["phase_currents_a"]), int(db["residual_currents_a"]), int(db["power_factor_pct"]),
        round(float(db["frequency_hz"]) * 10), int(db["powers"]), int(db["counters"]),
    ]

    scada = general["scada"]
    native_scada = native["s"]
    native_scada.update(
        s=int(bool(scada["enabled"])), p=_index(("DNP3", "IEC"), scada["protocol"]),
        d=_index(("ETHERNET", "RS232", "RS485", "MODEM"), scada["data_port"]),
    )
    dnp = scada["dnp3"]
    link = dnp["link"]
    native_scada["dn"]["l"].update(
        a=[int(link["slave_address"]), int(link["master_address"])], cr=int(link["confirm_retry"]),
        ct=_to_ms(link["confirm_timeout_s"]), k=_to_ms(link["keep_alive_s"]),
        cu=int(bool(link["confirm_user_data"])), ke=int(bool(link["keep_alive_enabled"])),
    )
    application = dnp["application"]
    native_scada["dn"]["a"].update(
        c=int(application["cold_restart_delay"]), w=int(application["warm_restart_delay"]),
        sc=_to_ms(application["solicited_confirm_timeout_s"]), st=_to_ms(application["select_timeout_s"]),
    )
    unsolicited = dnp["unsolicited"]
    native_unsolicited = native_scada["dn"]["u"]
    native_unsolicited.update(e=int(bool(unsolicited["enabled"])), h=int(unsolicited["hold_time_s"]))
    native_unsolicited["u"][1:4] = [int(bool(unsolicited[f"class_{i}"])) for i in range(1, 4)]
    timesync = dnp["time_sync"]
    native_scada["dn"]["t"].update(e=int(bool(timesync["enabled"])), r=_to_ms(timesync["request_interval_s"]))
    for index, name in enumerate(_DNP_CONFIG_NAMES):
        if name:
            native_scada["ma"][index] = _index(_DNP_MAP_OPTIONS[index], dnp["mapping"][name])
    if "i" in native_scada:
        _write_iec(scada["iec"], native_scada["i"])

    io = general["io"]
    native_io = system["io"]
    native_io["r"] = [
        _index(("SINGLE", "DOUBLE"), io["open_close"]["open_read_mode"]),
        _index(("SINGLE", "DOUBLE"), io["open_close"]["close_read_mode"]),
    ]
    native["onc"] = int(bool(io["open_close"]["open_need_confirm"]))
    native["cnc"] = int(bool(io["open_close"]["close_need_confirm"]))
    ethernet = io["ethernet"]
    native_io["e"].update(
        d=int(bool(ethernet["dhcp"])), i=_ip_parts(ethernet["ip"]),
        s=_ip_parts(ethernet["subnet_mask"]), g=_ip_parts(ethernet["gateway"]),
    )
    inputs = io["digital_inputs"]
    native_io["i"].update(
        c=int(bool(inputs["chatter_enabled"])), r=_to_ms(inputs["chatter_reset_s"]),
        v=_to_ms(inputs["validation_time_s"]),
        g=[_index(("DISABLE", "HIGH STATE", "LOW STATE"), value) for value in inputs["inputs"]],
    )
    for target, source in zip(native_io["o"][:7], io["digital_outputs"]):
        target.update(
            i=int(source["when"]), a=_index(("FALSE", "TRUE"), source["is"]),
            t=_to_ms(source["recognition_s"]),
            s=_index(("DISABLE", "LATCH ON", "PULSE ON"), source["then"]), o=_to_ms(source["for_s"]),
        )
    native_io["r2"] = _write_serial(scada["ports"]["rs232"])
    native_io["r4"] = _write_serial(scada["ports"]["rs485"])
    tcp = scada["ports"]["ethernet"]
    native_scada["dn"]["e"].update(
        m=_index(("SERVER", "CLIENT"), tcp["mode"]), l=int(tcp["local_port"]),
        r=int(tcp["remote_port"]), i=_ip_parts(tcp["remote_ip"]),
    )
    modem = scada["ports"]["modem"]
    native_io["m"].update(
        a=str(modem["apn"]), p=_index(("AUTO", "GSM", "LTE"), modem["network"]),
        b=_index(BAUD_RATES, str(modem["baudrate"])),
    )
    native_scada["dn"]["m"].update(
        m=_index(("SERVER", "CLIENT"), modem["mode"]), l=int(modem["local_port"]),
        r=int(modem["remote_port"]), i=_ip_parts(modem["remote_ip"]),
    )
    _write_global_system(general, native)
    _write_protection(config["protection"], native)


def _read_serial(target: dict[str, Any], source: list[Any]) -> None:
    target.update(
        baudrate=_choice(BAUD_RATES, source[0]), parity=_choice(_SERIAL_PARITY, source[1]),
        stop_bits=_choice(("1", "2"), source[2]), data_bits=_choice(("7", "8"), source[3]),
    )


def _write_serial(source: dict[str, Any]) -> list[int]:
    return [
        _index(BAUD_RATES, str(source["baudrate"])), _index(_SERIAL_PARITY, source["parity"]),
        _index(("1", "2"), str(source["stop_bits"])), _index(("7", "8"), str(source["data_bits"])),
    ]


def _read_iec(target: dict[str, Any], source: dict[str, Any]) -> None:
    general = target["general"]
    general.update(
        asdu_address_size=_choice(("1", "2"), source["as"]),
        ioa_size=_choice(("1", "2", "3"), source["is"]),
        cot_size=_choice(("1", "2"), source["cs"]),
        actterm=bool(source["ia"]),
        time_sync=bool(source["t"]),
        asdu_address=int(source["aa"]),
        originator_address=int(source["o"]),
    )
    for name, value in zip(_IEC_BASE_NAMES, source["b"]):
        target["base_addresses"][name] = int(value)

    iec101 = source["i1"]
    target["iec101"].update(
        channel_retry=int(iec101["c"]),
        rx_timeout_s=_ms(iec101["r"]),
        channel_mode=_choice(("BALANCED", "UNBALANCED"), iec101["m"]),
        link_address_size=_choice(("1", "2"), iec101["as"]),
        single_char_ack=bool(iec101["s"]),
        link_address=int(iec101["a"]),
        ack_timeout_s=_ms(iec101["at"]),
        repeat_timeout_s=_ms(iec101["rt"]),
    )
    iec104 = source["i4"]
    target["iec104"].update(
        **{f"timeout_{index}_s": _ms(value) for index, value in enumerate(iec104["t"])},
        k=int(iec104["k"]),
        w=int(iec104["w"]),
    )


def _write_iec(source: dict[str, Any], target: dict[str, Any]) -> None:
    general = source["general"]
    target.update(
        {
            "as": _index(("1", "2"), general["asdu_address_size"]),
            "is": _index(("1", "2", "3"), general["ioa_size"]),
            "cs": _index(("1", "2"), general["cot_size"]),
            "ia": int(bool(general["actterm"])),
            "t": int(bool(general["time_sync"])),
            "aa": int(general["asdu_address"]),
            "o": int(general["originator_address"]),
            "b": [int(source["base_addresses"][name]) for name in _IEC_BASE_NAMES],
        }
    )
    iec101 = source["iec101"]
    target["i1"].update(
        c=int(iec101["channel_retry"]),
        r=_to_ms(iec101["rx_timeout_s"]),
        m=_index(("BALANCED", "UNBALANCED"), iec101["channel_mode"]),
        **{
            "as": _index(("1", "2"), iec101["link_address_size"]),
            "s": int(bool(iec101["single_char_ack"])),
            "a": int(iec101["link_address"]),
            "at": _to_ms(iec101["ack_timeout_s"]),
            "rt": _to_ms(iec101["repeat_timeout_s"]),
        },
    )
    iec104 = source["iec104"]
    target["i4"].update(
        t=[_to_ms(iec104[f"timeout_{index}_s"]) for index in range(4)],
        k=int(iec104["k"]),
        w=int(iec104["w"]),
    )


def _read_global_system(general: dict[str, Any], native: dict[str, Any]) -> None:
    system = general["system"]
    fault = native["p"]["fl"]
    system["fault_locator"].update(
        enabled=bool(fault["e"]), r0=float(fault["v"][0]) / 1000,
        x0=float(fault["v"][1]) / 1000, r1=float(fault["v"][2]) / 1000,
        x1=float(fault["v"][3]) / 1000, line_length_km=float(fault["v"][4]) / 100,
    )
    sync = native["p"]["sy"]
    target = system["synchronization"]
    values = sync["g"]
    target.update(
        enabled=bool(values[0]),
        phase_selection=_choice(("PHASE TO GROUND", "PHASE TO PHASE"), values[1]),
        bus_and_line=_choice(("ABC/RST", "RST/ABC"), values[2]),
        dldb_autoreclose=bool(values[3]), dldb_manual_close=bool(values[4]),
        live_dead_autoreclose=_choice(("DISABLE", "LIVE BUS", "LIVE LINE", "LIVE/DEAD"), values[5]),
        live_dead_manual_close=_choice(("DISABLE", "LIVE BUS", "LIVE LINE", "LIVE/DEAD"), values[6]),
        live_bus_voltage_multiplier=float(values[7]) / 10, live_line_voltage_multiplier=float(values[8]) / 10,
        bus_max_voltage_multiplier=float(values[9]) / 10, line_max_voltage_multiplier=float(values[10]) / 10,
        voltage_difference_multiplier=float(values[11]) / 100,
        sync_enabled_for_recloser=bool(sync["c"]["s"][0]),
        max_slip_frequency_hz=float(sync["c"]["s"][1]) / 100,
        phase_angle_difference_deg=float(sync["c"]["s"][2]), manual_pre_sync_s=_ms(sync["c"]["t"]),
        fundamental_frequency_hz=float(sync["a"]["s"][0]),
        max_frequency_deviation_hz=float(sync["a"]["s"][1]) / 100,
        auto_max_slip_hz=float(sync["a"]["s"][2]) / 100,
        max_roc_slip_hz_s=float(sync["a"]["s"][3]) / 100,
        anti_motoring_s=bool(sync["a"]["s"][4]), waiting_time_s=_ms(sync["a"]["t"]),
    )
    for target_function, raw in zip(system["functions"], native["sy"].get("fn", ())):
        state = raw["s"]
        operands = raw["o"]
        target_function.update(
            enabled=bool(state[0]),
            value_type=_choice(_FUNCTION_TYPES, state[2]),
            operator=_choice(_DIGITAL_OPERATORS, state[3]),
            value_a=int(operands[0]),
            value_b=int(operands[1]),
            value_c=int(operands[2]),
            compared_to=_choice(("FALSE", "TRUE"), state[1]),
            analog_operator=_choice(_ANALOG_OPERATORS, state[4]),
            analog_value_a=int(operands[3]),
            analog_compared_to=int(raw["v"]),
            time_s=_ms(raw["t"]),
            action=_choice(_FUNCTION_ACTIONS, state[5]),
        )
    heater = native["sy"]["h"]
    general["heater"].update(enabled=bool(heater["s"]), on_temperature_c=int(heater["on"]), off_temperature_c=int(heater["of"]))
    security = general["security"]
    security.update(tls=bool(native["se"]["as"]), password=int(native["se"]["p"][0]), default_certificate=bool(native["cd"]))


def _write_global_system(general: dict[str, Any], native: dict[str, Any]) -> None:
    system = general["system"]
    fault = system["fault_locator"]
    native["p"]["fl"].update(
        e=int(bool(fault["enabled"])),
        v=[round(float(fault[name]) * 1000) for name in ("r0", "x0", "r1", "x1")] + [round(float(fault["line_length_km"]) * 100)],
    )
    source = system["synchronization"]
    sync = native["p"]["sy"]
    general_values = sync["g"]
    general_values[0] = int(bool(source["enabled"]))
    general_values[1] = _index(
        ("PHASE TO GROUND", "PHASE TO PHASE"), source["phase_selection"]
    )
    general_values[2:12] = [
        _index(("ABC/RST", "RST/ABC"), source["bus_and_line"]), int(bool(source["dldb_autoreclose"])),
        int(bool(source["dldb_manual_close"])),
        _index(("DISABLE", "LIVE BUS", "LIVE LINE", "LIVE/DEAD"), source["live_dead_autoreclose"]),
        _index(("DISABLE", "LIVE BUS", "LIVE LINE", "LIVE/DEAD"), source["live_dead_manual_close"]),
        round(float(source["live_bus_voltage_multiplier"]) * 10), round(float(source["live_line_voltage_multiplier"]) * 10),
        round(float(source["bus_max_voltage_multiplier"]) * 10), round(float(source["line_max_voltage_multiplier"]) * 10),
        round(float(source["voltage_difference_multiplier"]) * 100),
    ]
    sync["c"].update(
        s=[int(bool(source["sync_enabled_for_recloser"])), round(float(source["max_slip_frequency_hz"]) * 100), round(float(source["phase_angle_difference_deg"]))],
        t=_to_ms(source["manual_pre_sync_s"]),
    )
    sync["a"].update(
        s=[round(float(source["fundamental_frequency_hz"])), round(float(source["max_frequency_deviation_hz"]) * 100),
           round(float(source["auto_max_slip_hz"]) * 100), round(float(source["max_roc_slip_hz_s"]) * 100), int(bool(source["anti_motoring_s"]))],
        t=_to_ms(source["waiting_time_s"]),
    )
    native_functions = native["sy"].get("fn", [])
    for raw, function in zip(native_functions, system["functions"]):
        raw["t"] = _to_ms(function["time_s"])
        raw["v"] = int(function["analog_compared_to"])
        raw["o"] = [
            int(function["value_a"]),
            int(function["value_b"]),
            int(function["value_c"]),
            int(function["analog_value_a"]),
        ]
        raw["s"] = [
            int(bool(function["enabled"])),
            _index(("FALSE", "TRUE"), function["compared_to"]),
            _index(_FUNCTION_TYPES, function["value_type"]),
            _index(_DIGITAL_OPERATORS, function["operator"]),
            _index(_ANALOG_OPERATORS, function["analog_operator"]),
            _index(_FUNCTION_ACTIONS, function["action"]),
        ]
    heater = general["heater"]
    native["sy"]["h"].update(s=int(bool(heater["enabled"])), on=int(heater["on_temperature_c"]), of=int(heater["off_temperature_c"]))
    security = general["security"]
    native["se"]["as"] = int(bool(security["tls"]))
    native["se"]["p"][0] = int(security["password"])
    native["cd"] = int(bool(security["default_certificate"]))


def _read_protection(target: dict[str, Any], native: dict[str, Any]) -> None:
    protection = native["p"]
    enabled = protection["p"]
    target.update(
        enabled=bool(enabled[0]), sef_enabled=bool(enabled[1]), oc_enabled=bool(enabled[2]),
        ef_enabled=bool(enabled[3]), clp_enabled=bool(enabled[4]), inrush_enabled=bool(native["pi"]),
        frequency_enabled=bool(native["uf"]), voltage_enabled=bool(native["uv"]),
        live_line_enabled=bool(protection["le"]), active_group=int(protection["a"]) + 1,
    )
    flags = target["feature_flags"]
    for name, index in _FEATURE_INDEX.items():
        flags[name] = bool(protection["s"][index])
    flags.update(
        under_voltage=bool(native["uv"]), under_frequency=bool(native["uf"]),
        ir=bool(native["pi"]), live_line=bool(protection["le"]), sectionalizer=bool(native["sen"]),
    )
    for group, source in zip(target["groups"], protection["g"]):
        _read_group(group, source)
    overload = protection["ol"]
    for group in target["groups"]:
        item = group["master"]["overload"]
        item["negative_sequence_min_a"] = int(overload["n"])
        item["zero_sequence_min_a"] = int(overload["z"])
        for name, key in (("symmetrical", "s"), ("asymmetrical", "a")):
            raw = overload[key]
            item[name].update(
                mode=_choice(_PROTECTION_MODES, raw["m"]),
                pickup_a=int(raw["i"]), trip_s=_ms(raw["t"]), reset_s=_ms(raw["r"]),
            )


def _write_protection(source: dict[str, Any], native: dict[str, Any]) -> None:
    protection = native["p"]
    protection["p"] = [
        int(bool(source["enabled"])), int(bool(source["sef_enabled"])), int(bool(source["oc_enabled"])),
        int(bool(source["ef_enabled"])), int(bool(source["clp_enabled"])),
    ]
    protection["a"] = max(0, min(3, int(source["active_group"]) - 1))
    native["pi"] = int(bool(source["inrush_enabled"]))
    native["uf"] = int(bool(source["frequency_enabled"]))
    native["uv"] = int(bool(source["voltage_enabled"]))
    protection["le"] = int(bool(source["live_line_enabled"]))
    native["sen"] = int(bool(source["feature_flags"]["sectionalizer"]))
    for name, index in _FEATURE_INDEX.items():
        protection["s"][index] = int(bool(source["feature_flags"][name]))
    for group, target in zip(source["groups"], protection["g"]):
        _write_group(group, target)
    active = source["groups"][protection["a"]]
    overload = active["master"]["overload"]
    native_overload = protection["ol"]
    native_overload["n"] = int(overload["negative_sequence_min_a"])
    native_overload["z"] = int(overload["zero_sequence_min_a"])
    for name, key in (("symmetrical", "s"), ("asymmetrical", "a")):
        item = overload[name]
        native_overload[key].update(
            m=_index(_PROTECTION_MODES, item["mode"]), i=int(item["pickup_a"]),
            t=_to_ms(item["trip_s"]), r=_to_ms(item["reset_s"]),
        )


def _read_group(target: dict[str, Any], source: dict[str, Any]) -> None:
    for name, key in (("oc", "o"), ("ef", "e"), ("nps", "nps")):
        _read_ocef(target[name], source[key])
    maximums = source.get("cm", [500] * 6)
    for offset, name in enumerate(("oc", "ef", "nps")):
        for direction, element_index in enumerate((1, 4)):
            raw_index = offset * 2 + direction
            if raw_index < len(maximums):
                target[name]["elements"][element_index]["max_current_multiplier"] = (
                    float(maximums[raw_index]) / 100
                )
    _read_sef(target["sef"], source["sf"])
    target["clp"].update(multiplier=float(source["c"]["c"]), time_min=round(_ms(source["c"]["t"]) / 60), recognition_min=round(_ms(source["c"]["r"]) / 60))
    target["inrush"].update(multiplier=float(source["i"]["i"]), time_s=_ms(source["i"]["t"]))
    target["sectionalizing"].update(
        state=_choice(("ALARM", "TRIP/LOCK"), source["sc"].get("s", 0)),
        max_trip_count=int(source["sc"]["t"]),
        reset_time_s=_ms(source["sc"]["r"]),
    )
    for name, key in (("oc", "o"), ("ef", "e")):
        target["live_line"][name].update(pickup_a=int(source["ll"][key]["i"]), tripping_time_s=_ms(source["ll"][key]["tt"]))
    recloser = source["r"]
    times = recloser["oe"]["t"]
    target["ar_ocef"].update(
        reclose_1_s=_ms(times[0]), reclose_2_s=_ms(times[1]), reclose_3_s=_ms(times[2]),
        reset_s=_ms(times[3]), vrc=bool(recloser["oe"]["v"]),
        lsrm_mode=_choice(("DISABLE", "ENABLE"), recloser["oe"]["le"]), lsrm_time_s=_ms(recloser["oe"]["lt"]),
    )
    target["recloser_enabled"] = bool(recloser["e"])
    _read_voltage(target, source)
    _read_extensions(target, source)


def _write_group(source: dict[str, Any], target: dict[str, Any]) -> None:
    for name, key in (("oc", "o"), ("ef", "e"), ("nps", "nps")):
        _write_ocef(source[name], target[key])
    if "cm" in target:
        target["cm"] = [round(float(source[name]["elements"][index]["max_current_multiplier"]) * 100)
                        for name in ("oc", "ef", "nps") for index in (1, 4)]
    if "s" in target["sc"]:
        target["sc"]["s"] = _index(("ALARM", "TRIP/LOCK"), source["sectionalizing"]["state"])
    _write_sef(source["sef"], target["sf"])
    target["c"].update(c=float(source["clp"]["multiplier"]), t=_to_ms(float(source["clp"]["time_min"]) * 60), r=_to_ms(float(source["clp"]["recognition_min"]) * 60))
    target["i"].update(i=float(source["inrush"]["multiplier"]), t=_to_ms(source["inrush"]["time_s"]))
    target["sc"].update(
        t=int(source["sectionalizing"]["max_trip_count"]),
        r=_to_ms(source["sectionalizing"]["reset_time_s"]),
    )
    for name, key in (("oc", "o"), ("ef", "e")):
        target["ll"][key].update(i=int(source["live_line"][name]["pickup_a"]), tt=_to_ms(source["live_line"][name]["tripping_time_s"]))
    ar = source["ar_ocef"]
    target["r"]["oe"].update(
        t=[_to_ms(ar[name]) for name in ("reclose_1_s", "reclose_2_s", "reclose_3_s", "reset_s")],
        v=int(bool(ar["vrc"])), le=_index(("DISABLE", "ENABLE"), ar["lsrm_mode"]), lt=_to_ms(ar["lsrm_time_s"]),
    )
    target["r"]["e"] = int(bool(source["recloser_enabled"]))
    _write_voltage(source, target)
    _write_extensions(source, target)


def _read_ocef(target: dict[str, Any], source: dict[str, Any]) -> None:
    elements = target["elements"]
    for index, item in enumerate((source["f"]["d"], source["f"]["f"], source["f"]["h"], source["r"]["d"], source["r"]["f"], source["r"]["h"])):
        _read_element(elements[index], item, index % 3 == 2, index % 3 == 1)
    target["torque_angle_deg"] = int(source["at"])


def _write_ocef(source: dict[str, Any], target: dict[str, Any]) -> None:
    for index, item in enumerate((target["f"]["d"], target["f"]["f"], target["f"]["h"], target["r"]["d"], target["r"]["f"], target["r"]["h"])):
        _write_element(source["elements"][index], item, index % 3 == 2, index % 3 == 1)
    target["at"] = int(source["torque_angle_deg"])


def _read_element(
    target: dict[str, Any], source: dict[str, Any], highset: bool, fast_trip: bool
) -> None:
    values = source if highset else source["t"]
    target.update(
        enabled=bool(source["e"]), pickup_a=int(values["i"]), tripping_time_s=_ms(values["tt"]),
        ar_modes=[_choice(AR_MODES, value) for value in source["a"]],
    )
    if not highset:
        target.update(
            type=_choice(TCC_TYPES, values["t"]), time_multiplier=float(values["tm"]),
            min_current_multiplier=float(values["mi"]), definite_min_time_s=_ms(values["tmi"]),
            max_tripping_time_s=_ms(values["tma"]), time_adder_s=_ms(values["ta"]), reset_time_s=_ms(values["tr"]),
        )
        if fast_trip:
            target["max_mode"] = bool(values.get("mm", 0))


def _write_element(
    source: dict[str, Any], target: dict[str, Any], highset: bool, fast_trip: bool
) -> None:
    values = target if highset else target["t"]
    target["e"] = int(bool(source["enabled"]))
    target["a"] = [_index(AR_MODES, value) for value in source["ar_modes"]]
    values.update(i=int(source["pickup_a"]), tt=_to_ms(source["tripping_time_s"]))
    if not highset:
        values.update(
            t=_index(TCC_TYPES, source["type"]), tm=float(source["time_multiplier"]), mi=float(source["min_current_multiplier"]),
            tmi=_to_ms(source["definite_min_time_s"]), tma=_to_ms(source["max_tripping_time_s"]),
            ta=_to_ms(source["time_adder_s"]), tr=_to_ms(source["reset_time_s"]),
        )
        if fast_trip and "mm" in values:
            values["mm"] = int(bool(source["max_mode"]))


def _read_sef(target: dict[str, Any], source: dict[str, Any]) -> None:
    for item, native_item in zip(target["elements"], (source["f"], source["r"])):
        item.update(enabled=bool(native_item["e"]), pickup_a=int(native_item["i"]), tripping_time_s=_ms(native_item["tt"]), reset_time_s=_ms(native_item["tr"]), ar_modes=[_choice(AR_MODES, value) for value in native_item["a"]])
    target["torque_angle_deg"] = int(source["at"])


def _write_sef(source: dict[str, Any], target: dict[str, Any]) -> None:
    for item, native_item in zip(source["elements"], (target["f"], target["r"])):
        native_item.update(e=int(bool(item["enabled"])), i=int(item["pickup_a"]), tt=_to_ms(item["tripping_time_s"]), tr=_to_ms(item["reset_time_s"]), a=[_index(AR_MODES, value) for value in item["ar_modes"]])
    target["at"] = int(source["torque_angle_deg"])


def _read_voltage(target: dict[str, Any], source: dict[str, Any]) -> None:
    voltage = target["voltage"]
    for index, name in enumerate(("uv1", "uv2", "uv3", "uv12", "uv13", "uv22", "uv23")):
        if index >= len(source["uv"]["u"]):
            break
        item = source["uv"]["u"][index]
        voltage[name].update(multiplier=float(item["u"]) / 100, trip_s=_ms(item["t"]), ar_mode=_choice(AR_MODES, item["a"]))
    voltage.update(auto_close_enabled=bool(source["uv"]["f"][0]), auto_close_s=_ms(source["uv"]["c"]), reclose_s=_ms(source["uv"]["r"]))
    ov = source["ov"][0]
    voltage["ov"].update(multiplier=float(ov["u"]) / 100, trip_s=_ms(ov["t"]), ar_mode=_choice(AR_MODES, ov["a"]), reclose_s=_ms(source["uv"]["r"]))
    uf = source["f"]["u"]
    target["under_frequency"].update(pickup_hz=float(uf["p"]) / 100, trip_s=_ms(uf["t"]), ar_mode=_choice(AR_MODES, uf["m"]))
    abr = source["a"]
    target["abr"].update(enabled=bool(abr["e"]), reset_s=_ms(abr["rt"]), auto_open_mode=_choice(_AUTO_OPEN_MODES, abr["a"]))
    target["abr"]["timer"].update(time_min=round(_ms(abr["ot"]) / 60), operations=int(abr["oo"]))
    target["abr"]["power_flow"].update(direction_changed=bool(abr["d"]), reduced=bool(abr["r"]), reduced_percent=int(abr["or"]), time_s=_ms(abr["op"]))


def _write_voltage(source: dict[str, Any], target: dict[str, Any]) -> None:
    voltage = source["voltage"]
    for index, name in enumerate(("uv1", "uv2", "uv3", "uv12", "uv13", "uv22", "uv23")):
        if index >= len(target["uv"]["u"]):
            break
        item = voltage[name]
        target["uv"]["u"][index].update(u=round(float(item["multiplier"]) * 100), t=_to_ms(item["trip_s"]), a=_index(AR_MODES, item["ar_mode"]))
    target["uv"].update(c=_to_ms(voltage["auto_close_s"]), r=_to_ms(voltage["reclose_s"]))
    target["uv"]["f"][0] = int(bool(voltage["auto_close_enabled"]))
    ov = voltage["ov"]
    target["ov"][0].update(u=round(float(ov["multiplier"]) * 100), t=_to_ms(ov["trip_s"]), a=_index(AR_MODES, ov["ar_mode"]))
    uf = source["under_frequency"]
    target["f"]["u"].update(p=round(float(uf["pickup_hz"]) * 100), t=_to_ms(uf["trip_s"]), m=_index(AR_MODES, uf["ar_mode"]))
    abr = source["abr"]
    target["a"].update({
        "e": int(bool(abr["enabled"])), "rt": _to_ms(abr["reset_s"]),
        "a": _index(_AUTO_OPEN_MODES, abr["auto_open_mode"]),
        "ot": _to_ms(float(abr["timer"]["time_min"]) * 60), "oo": int(abr["timer"]["operations"]),
        "d": int(bool(abr["power_flow"]["direction_changed"])), "r": int(bool(abr["power_flow"]["reduced"])),
        "or": int(abr["power_flow"]["reduced_percent"]), "op": _to_ms(abr["power_flow"]["time_s"]),
    })


def _read_extensions(target: dict[str, Any], source: dict[str, Any]) -> None:
    master = target["master"]
    for index, name in enumerate(("oc", "ef", "nps", "sef")):
        raw = source["d"][index]
        item = master["directional"][name]
        item.update(
            torque_angle_deg=int(source[{"oc": "o", "ef": "e", "nps": "nps", "sef": "sf"}[name]]["at"]),
            not_detected=_choice(("BLOCK", "TRIP"), raw[0]),
            change_response=_choice(("LOCK", "DYNAMIC"), raw[1]), stages=[bool(value) for value in raw[2:]],
        )
    admittance = source["ad"]
    item = master["admittance"]
    item.update(
        ar_modes=[_choice(AR_MODES, value) for value in admittance["a"][:4]],
        operational_mode=_choice(("GN", "BN", "GN&BN"), admittance["a"][4]),
        directional_mode=_choice(("FORWARD", "REVERSE", "ANY"), admittance["a"][5]),
        min_un_multiplier=float(admittance["a"][6]) / 100, trip_s=_ms(admittance["b"][0]),
        reset_s=_ms(admittance["b"][1]), minimum_in_a=float(admittance["c"][0]),
        forward_susceptance=float(admittance["c"][1]) / 100, reverse_susceptance=float(admittance["c"][2]) / 100,
        forward_conductance=float(admittance["c"][3]) / 100, reverse_conductance=float(admittance["c"][4]) / 100,
    )
    harmonic = source["h"]
    inrush = target["inrush"]
    inrush.update(
        second_harmonic_enabled=bool(source["i"]["h"][0][0]), second_harmonic_level_pct=float(source["i"]["h"][0][1]),
        second_harmonic_time_s=_ms(source["i"]["h"][0][2]), fifth_harmonic_enabled=bool(source["i"]["h"][1][0]),
        fifth_harmonic_level_pct=float(source["i"]["h"][1][1]), fifth_harmonic_time_s=_ms(source["i"]["h"][1][2]),
        sst_control_enabled=bool(source["sst"]["e"]), sst_control_time_s=_ms(source["sst"]["t"]),
    )
    for name, key in (("thd", "h"), ("tdd", "d")):
        raw = harmonic["t"][key]
        master["harmonic"][name].update(mode=_choice(_PROTECTION_MODES, raw["m"]), level_pct=float(raw["l"]) / 10, trip_s=_ms(raw["t"]))
    individual = master["harmonic"]["individual"]
    individual.update(mode=_choice(_PROTECTION_MODES, harmonic["i"]["m"]), trip_s=_ms(harmonic["i"]["t"]))
    for item, raw in zip(individual["items"], harmonic["i"]["s"]):
        item.update(
            mode=_choice(_INDIVIDUAL_HARMONICS, raw["m"]),
            level_pct=float(raw["l"]) / 10,
        )
    over_voltage = master["over_voltage"]
    for index, name in enumerate(("ov1", "ov2", "ov3", "ov4", "ov12", "ov13", "ov22", "ov23")):
        if index >= len(source["ov"]):
            break
        raw = source["ov"][index]
        over_voltage[name].update(multiplier=float(raw["u"]) / 100, trip_s=_ms(raw["t"]), ar_mode=_choice(AR_MODES, raw["a"]))
    over_voltage["ov3"].update(moving_average_mode=_choice(("DISABLE", "ENABLE"), source["ov"][2]["mam"]), moving_average_window=_ms(source["ov"][2]["maw"]))
    ar_voltage = master["ar_voltage"]
    ar_voltage.update(reclose_s=_ms(source["uv"]["r"]), trip_count=int(source["uv"]["f"][2]), sst_only=bool(source["uv"]["f"][1]), auto_close=bool(source["uv"]["f"][0]), auto_close_s=_ms(source["uv"]["c"]))
    for index, name in enumerate(("uv1", "uv2", "uv3", "uv12", "uv13", "uv22", "uv23")):
        if index >= len(source["uv"]["u"]):
            break
        ar_voltage[name] = _choice(AR_MODES, source["uv"]["u"][index]["a"])
    for index, name in enumerate(("ov1", "ov2", "ov3", "ov4", "ov12", "ov13", "ov22", "ov23")):
        if index >= len(source["ov"]):
            break
        ar_voltage[name] = _choice(AR_MODES, source["ov"][index]["a"])
    frequency = master["frequency"]
    for name, key in (("under", "u"), ("over", "o")):
        raw = source["f"][key]
        frequency[name].update(mode=_choice(_PROTECTION_MODES, raw["m"]), pickup_hz=float(raw["p"]) / 100, trip_s=_ms(raw["t"]))
    frequency["vrc"].update(mode=_choice(("ABC", "RST", "RING"), source["r"]["v"][0]), voltage_multiplier=float(source["r"]["v"][1]) / 100)
    frequency["llb"].update(mode=bool(source["r"]["l"][0]), voltage_multiplier=float(source["r"]["l"][1]) / 100)
    bc = source["bc"]
    master["broken_conductor"].update(mode=_choice(_PROTECTION_MODES, bc["m"]), pickup_pct=int(bc["p"]), negative_sequence_min_a=int(bc["n"]), trip_s=_ms(bc["t"]))


def _write_extensions(source: dict[str, Any], target: dict[str, Any]) -> None:
    master = source["master"]
    for index, name in enumerate(("oc", "ef", "nps", "sef")):
        item = master["directional"][name]
        raw = target["d"][index]
        raw[0] = _index(("BLOCK", "TRIP"), item["not_detected"])
        raw[1] = _index(("LOCK", "DYNAMIC"), item["change_response"])
        raw[2:] = [int(bool(value)) for value in item["stages"]]
    item = master["admittance"]
    target["ad"]["a"] = [_index(AR_MODES, value) for value in item["ar_modes"]] + [
        _index(("GN", "BN", "GN&BN"), item["operational_mode"]),
        _index(("FORWARD", "REVERSE", "ANY"), item["directional_mode"]),
        round(float(item["min_un_multiplier"]) * 100),
    ]
    target["ad"]["b"] = [_to_ms(item["trip_s"]), _to_ms(item["reset_s"])]
    target["ad"]["c"] = [int(item["minimum_in_a"])] + [round(float(item[name]) * 100) for name in ("forward_susceptance", "reverse_susceptance", "forward_conductance", "reverse_conductance")]
    inrush = source["inrush"]
    target["i"]["h"] = [
        [int(bool(inrush["second_harmonic_enabled"])), round(float(inrush["second_harmonic_level_pct"])), _to_ms(inrush["second_harmonic_time_s"])],
        [int(bool(inrush["fifth_harmonic_enabled"])), round(float(inrush["fifth_harmonic_level_pct"])), _to_ms(inrush["fifth_harmonic_time_s"])],
    ]
    target["sst"].update(e=int(bool(inrush["sst_control_enabled"])), t=_to_ms(inrush["sst_control_time_s"]))
    harmonic = master["harmonic"]
    for name, key in (("thd", "h"), ("tdd", "d")):
        item = harmonic[name]
        target["h"]["t"][key].update(m=_index(_PROTECTION_MODES, item["mode"]), l=round(float(item["level_pct"]) * 10), t=_to_ms(item["trip_s"]))
    individual = harmonic["individual"]
    target["h"]["i"].update(m=_index(_PROTECTION_MODES, individual["mode"]), t=_to_ms(individual["trip_s"]))
    for raw, item in zip(target["h"]["i"]["s"], individual["items"]):
        raw.update(
            m=_index(_INDIVIDUAL_HARMONICS, item["mode"]),
            l=round(float(item["level_pct"]) * 10),
        )
    over_voltage = master["over_voltage"]
    for index, name in enumerate(("ov1", "ov2", "ov3", "ov4", "ov12", "ov13", "ov22", "ov23")):
        if index >= len(target["ov"]):
            break
        item = over_voltage[name]
        target["ov"][index].update(u=round(float(item["multiplier"]) * 100), t=_to_ms(item["trip_s"]), a=_index(AR_MODES, item["ar_mode"]))
    target["ov"][2].update(mam=_index(("DISABLE", "ENABLE"), over_voltage["ov3"]["moving_average_mode"]), maw=_to_ms(over_voltage["ov3"]["moving_average_window"]))
    ar = master["ar_voltage"]
    target["uv"].update(r=_to_ms(ar["reclose_s"]), c=_to_ms(ar["auto_close_s"]))
    target["uv"]["f"] = [int(bool(ar["auto_close"])), int(bool(ar["sst_only"])), int(ar["trip_count"])]
    for index, name in enumerate(("uv1", "uv2", "uv3", "uv12", "uv13", "uv22", "uv23")):
        if index >= len(target["uv"]["u"]):
            break
        target["uv"]["u"][index]["a"] = _index(AR_MODES, ar[name])
    for index, name in enumerate(("ov1", "ov2", "ov3", "ov4", "ov12", "ov13", "ov22", "ov23")):
        if index >= len(target["ov"]):
            break
        target["ov"][index]["a"] = _index(AR_MODES, ar[name])
    frequency = master["frequency"]
    for name, key in (("under", "u"), ("over", "o")):
        item = frequency[name]
        target["f"][key].update(m=_index(_PROTECTION_MODES, item["mode"]), p=round(float(item["pickup_hz"]) * 100), t=_to_ms(item["trip_s"]))
    target["r"]["v"] = [_index(("ABC", "RST", "RING"), frequency["vrc"]["mode"]), round(float(frequency["vrc"]["voltage_multiplier"]) * 100)]
    target["r"]["l"][0] = int(bool(frequency["llb"]["mode"]))
    target["r"]["l"][1] = round(float(frequency["llb"]["voltage_multiplier"]) * 100)
    bc = master["broken_conductor"]
    target["bc"].update(m=_index(_PROTECTION_MODES, bc["mode"]), p=int(bc["pickup_pct"]), n=int(bc["negative_sequence_min_a"]), t=_to_ms(bc["trip_s"]))
