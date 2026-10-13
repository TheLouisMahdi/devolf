"""Master numeric editing, packed wire bounds and lossless load/save regressions."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from wolfeye.config_schema import default_config
from wolfeye.numeric_schema import numeric_spec, TIME
from wolfeye.qt import QApplication, QDoubleSpinBox, QSpinBox
from wolfeye.services.beacheye import default_settings_file, decode_settings_payload, patch_settings_payload
from wolfeye.services.native_config import update_config_from_native, update_native_from_config
from wolfeye.widgets.config_pages import GeneralPage, ProtectionPage, _get_path, _set_path


class NumericSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_bound_numeric_editor_has_storage_limits(self):
        for page in (GeneralPage(), ProtectionPage()):
            for path, widgets in page._bindings.items():
                for widget in widgets:
                    if not isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                        continue
                    with self.subTest(path=path):
                        spec = numeric_spec(path)
                        self.assertIsNotNone(spec)
                        self.assertEqual(widget.minimum(), spec.minimum)
                        self.assertEqual(widget.maximum(), spec.maximum)
                        if isinstance(widget, QDoubleSpinBox):
                            self.assertEqual(widget.decimals(), spec.decimals)
            page.close()

    def test_extended_values_survive_ui_and_native_wire_round_trip(self):
        for model in ("FC22AR", "FC22S"):
            payload = default_settings_file(model)[:-3]
            native = decode_settings_payload(payload, model)
            config = default_config()
            update_config_from_native(config, native)
            edits = {
                "general.measurement.rated_voltage_v": 65535,
                "general.measurement.coefficients.line_a": 65000,
                "general.measurement.deadbands.voltages_v": 0.123,
                "general.system.lsd_level": 2.345,
                "general.scada.dnp3.link.confirm_timeout_s": TIME.maximum,
                "general.scada.dnp3.unsolicited.hold_time_s": 255,
                "general.io.digital_inputs.validation_time_s": 0.255,
                "general.io.digital_outputs.0.recognition_s": 180.123,
                "general.io.digital_outputs.0.for_s": 250.456,
                "general.system.functions.0.analog_compared_to": 4294967295,
                "general.system.synchronization.live_bus_voltage_multiplier": 1.5,
                "general.system.synchronization.max_slip_frequency_hz": 0.15,
                "general.heater.on_temperature_c": 255,
                "general.security.password": 4294967295,
                "protection.groups.0.oc.elements.1.pickup_a": 65000,
                "protection.groups.0.oc.elements.1.tripping_time_s": 250.123,
            }
            if model == "FC22AR":
                edits.update({
                    "protection.groups.0.oc.elements.0.time_multiplier": 20.125,
                    "protection.groups.0.ef.elements.0.reset_time_s": 5.123,
                    "protection.groups.0.voltage.uv12.multiplier": 2.55,
                    "protection.groups.0.master.over_voltage.ov1.multiplier": 3.5,
                    "protection.groups.0.master.over_voltage.ov3.moving_average_window": 0.125,
                    "protection.groups.0.master.admittance.forward_conductance": -327.68,
                    "protection.groups.0.master.admittance.reverse_conductance": 327.67,
                    "protection.groups.0.abr.timer.operations": 15,
                    "protection.groups.0.master.ar_voltage.trip_count": 15,
                })
            else:
                edits["protection.groups.0.sef.elements.1.pickup_a"] = 1000
                edits["protection.groups.0.sef.elements.1.reset_time_s"] = 20.123
            for path, value in edits.items():
                _set_path(config, path, value)
            pages = (GeneralPage(), ProtectionPage())
            for page in pages:
                page.set_device_model(model)
                page.apply_config(config)
                page.update_config(config)
                page.close()
            update_native_from_config(native, config)
            decoded = decode_settings_payload(patch_settings_payload(payload, native, model), model)
            result = default_config()
            update_config_from_native(result, decoded)
            for path, value in edits.items():
                with self.subTest(model=model, path=path):
                    self.assertAlmostEqual(_get_path(result, path), value, places=5)

    def test_overflow_is_rejected_before_native_settings_are_changed(self):
        native = decode_settings_payload(default_settings_file("FC22AR")[:-3], "FC22AR")
        original = deepcopy(native)
        for path, value in (
            ("general.measurement.rated_voltage_v", 65536),
            ("general.system.synchronization.live_bus_voltage_multiplier", 1.6),
            ("general.system.synchronization.max_slip_frequency_hz", 0.16),
            ("general.system.functions.0.analog_compared_to", 4294967296),
            ("protection.groups.0.voltage.uv12.multiplier", 2.56),
            ("protection.groups.0.oc.elements.0.tripping_time_s", float("inf")),
            ("protection.groups.0.oc.elements.0.time_multiplier", float("nan")),
        ):
            config = default_config()
            _set_path(config, path, value)
            with self.subTest(path=path), self.assertRaises(ValueError):
                update_native_from_config(native, config)
            self.assertEqual(native, original)

    def test_untouched_float_precision_is_preserved_when_another_field_changes(self):
        config = default_config()
        config["protection"]["groups"][0]["oc"]["elements"][0]["time_multiplier"] = 1.23456789
        page = ProtectionPage()
        page.apply_config(config)
        page._bindings["protection.groups.0.oc.elements.0.pickup_a"][0].setValue(7000)
        page.update_config(config)
        self.assertEqual(config["protection"]["groups"][0]["oc"]["elements"][0]["time_multiplier"], 1.23456789)
        page.close()

    def test_tcc_selection_and_edit_do_not_restore_engineering_caps(self):
        config = default_config()
        element = config["protection"]["groups"][0]["oc"]["elements"][1]
        element.update(enabled=True, pickup_a=7000, tripping_time_s=250.123, reset_time_s=5.123)
        page = ProtectionPage()
        page.apply_config(config)
        dialog = page._open_tcc_dialog("OC", "protection.groups.0.oc", page.ELEMENT_NAMES, 1)
        self.assertEqual(dialog.pickup.value(), 7000)
        self.assertEqual(dialog.trip_time.value(), 250.123)
        self.assertEqual(dialog.reset_time.value(), 5.123)
        dialog.pickup.setValue(8000)
        dialog.elements_list.setCurrentRow(0)
        dialog.elements_list.setCurrentRow(1)
        dialog.close()
        self.assertEqual(element["pickup_a"], 8000)
        self.assertEqual(element["tripping_time_s"], 250.123)
        self.assertEqual(element["reset_time_s"], 5.123)
        page.close()


if __name__ == "__main__":
    unittest.main()
