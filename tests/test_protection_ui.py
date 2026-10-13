"""Company-compatible protection menus and TCC curve tests."""

from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from wolfeye.qt import (  # noqa: E402
    QApplication,
    QAbstractSpinBox,
    QComboBox,
    QSpinBox,
    QTableWidget,
    Qt,
)

from wolfeye.config_schema import default_config  # noqa: E402
from wolfeye.numeric_schema import TIME  # noqa: E402
from wolfeye.services.beacheye import (  # noqa: E402
    decode_settings_payload,
    default_settings_file,
    patch_settings_payload,
)
from wolfeye.services.native_config import (  # noqa: E402
    update_config_from_native,
    update_native_from_config,
)
from wolfeye.styles import V2_COMPACT_STYLE, V2_STYLE_SHEET  # noqa: E402
from wolfeye.widgets.config_pages import GeneralPage, ProtectionPage  # noqa: E402
from wolfeye.widgets.tcc_chart import calculate_trip_time_s  # noqa: E402


class TccCalculatorTests(unittest.TestCase):
    def test_ansi_curve_matches_company_formula(self) -> None:
        element = {
            "type": "ANSI EI",
            "pickup_a": 100,
            "time_multiplier": 1.2,
            "definite_min_time_s": 0.0,
            "max_tripping_time_s": 120.0,
            "time_adder_s": 0.15,
        }
        expected = int(
            (6.407 / (math.pow(3.0, 2.0) - 1.0) + 0.025) * 1.2 * 1000
        ) / 1000

        self.assertEqual(calculate_trip_time_s(element, 300), expected)

    def test_definite_time_matches_company_behavior_below_pickup(self) -> None:
        element = {"type": "TD", "pickup_a": 100, "tripping_time_s": 1.25}

        self.assertEqual(calculate_trip_time_s(element, 20), 1.25)

    def test_iec_curve_respects_company_minimum_and_maximum(self) -> None:
        element = {
            "type": "IEC VI",
            "pickup_a": 100,
            "time_multiplier": 1.0,
            "definite_min_time_s": 0.25,
            "max_tripping_time_s": 4.0,
            "time_adder_s": 0.0,
        }

        self.assertEqual(calculate_trip_time_s(element, 101), 4.0)
        self.assertGreaterEqual(calculate_trip_time_s(element, 5000), 0.25)
        self.assertEqual(calculate_trip_time_s(element, 100), 4.0)


class ProtectionMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.page = ProtectionPage()
        self.page.apply_config(default_config())

    def visible_tabs(self) -> list[str]:
        tabs = self.page._group_tabs[0]
        return [
            tabs.tabText(index)
            for index in range(tabs.count())
            if tabs.isTabVisible(index)
        ]

    def test_recloser_uses_company_specific_menu(self) -> None:
        self.page.set_device_model("FC22AR")

        self.assertEqual(
            self.visible_tabs(),
            [
                "OCEF / TCC",
                "NPS",
                "SEF / Reclosing",
                "Auxiliary",
                "Voltage / Frequency / ABR",
                "Master Extensions",
            ],
        )
        self.assertFalse(self.page._feature_widgets["nps"].isHidden())
        self.assertTrue(self.page._feature_widgets["sectionalizer"].isHidden())

    def test_sectionalizer_uses_company_specific_menu(self) -> None:
        self.page.show()
        self.page.set_device_model("FC22S")

        self.assertEqual(
            self.visible_tabs(),
            ["Protection", "Sectionalizing / Breaker", "Voltage / BC46"],
        )
        self.assertFalse(self.page._feature_widgets["sectionalizer"].isHidden())
        self.assertFalse(self.page._feature_widgets["breaker"].isHidden())
        self.assertTrue(self.page._feature_widgets["nps"].isHidden())
        synchronism = self.page._global_widgets["live_line_enabled"]
        self.assertFalse(synchronism.isHidden())
        self.assertEqual(synchronism.text(), "Enable Synchronism")

    def test_shared_fields_stay_synchronized_between_device_views(self) -> None:
        path = "protection.groups.0.master.broken_conductor.mode"
        widgets = self.page._bindings[path]
        self.assertGreaterEqual(len(widgets), 2)
        self.assertTrue(all(isinstance(widget, QComboBox) for widget in widgets))

        widgets[0].setCurrentText("TRIP")

        self.assertTrue(all(widget.currentText() == "TRIP" for widget in widgets))

    def test_sectionalizer_state_is_editable_and_bound(self) -> None:
        path = "protection.groups.0.sectionalizing.state"
        widgets = self.page._bindings[path]
        self.assertGreaterEqual(len(widgets), 1)

        widgets[0].setCurrentText("TRIP/LOCK")

        config = default_config()
        self.page.update_config(config)
        self.assertEqual(
            config["protection"]["groups"][0]["sectionalizing"]["state"],
            "TRIP/LOCK",
        )

    def test_sectionalizer_voltage_modes_use_company_labels_and_native_values(self) -> None:
        path = "protection.groups.0.master.ar_voltage.uv1"
        mode = next(
            widget
            for widget in self.page._bindings[path]
            if widget.property("bindItemData")
        )
        self.assertEqual(
            [mode.itemText(index) for index in range(mode.count())],
            ["DISABLE", "ALARM", "TRIP"],
        )

        mode.setCurrentText("TRIP")
        config = default_config()
        self.page.update_config(config)

        self.assertEqual(config["protection"]["groups"][0]["master"]["ar_voltage"]["uv1"], "RECLOSE")
        self.assertNotIn(
            "protection.groups.0.voltage.uv3.multiplier",
            self.page._bindings,
        )

    def test_tcc_dialog_opens_for_an_element(self) -> None:
        dialog = self.page._open_tcc_dialog(
            "Phase Overcurrent (OC)",
            "protection.groups.0.oc",
            self.page.ELEMENT_NAMES,
            0,
        )

        self.assertIsNotNone(dialog)
        self.assertIn("Protection Curve", dialog.windowTitle())
        self.assertEqual(dialog.elements_list.count(), 6)
        dialog.close()

    def test_new_voltage_stages_and_fast_trip_limit_are_bound(self) -> None:
        for path in (
            "protection.groups.0.voltage.uv12.trip_s",
            "protection.groups.0.voltage.uv23.trip_s",
            "protection.groups.0.master.over_voltage.ov12.multiplier",
            "protection.groups.0.master.over_voltage.ov23.multiplier",
            "protection.groups.0.master.ar_voltage.uv23",
            "protection.groups.0.master.ar_voltage.ov23",
            "protection.groups.0.oc.elements.1.max_mode",
            "protection.groups.0.oc.elements.1.max_current_multiplier",
        ):
            self.assertIn(path, self.page._bindings)

        delayed_max = self.page._bindings[
            "protection.groups.0.oc.elements.0.max_mode"
        ][0]
        fast_curve = self.page._bindings[
            "protection.groups.0.oc.elements.1.type"
        ][0]
        fast_max = self.page._bindings[
            "protection.groups.0.oc.elements.1.max_mode"
        ][0]
        fast_limit = self.page._bindings[
            "protection.groups.0.oc.elements.1.max_current_multiplier"
        ][0]

        self.assertFalse(delayed_max.isEnabled())
        fast_curve.setCurrentText("IEC VI")
        fast_max.setChecked(True)
        self.assertTrue(fast_max.isEnabled())
        self.assertTrue(fast_limit.isEnabled())

    def test_tcc_dialog_edits_are_returned_to_the_main_table(self) -> None:
        dialog = self.page._open_tcc_dialog(
            "Phase Overcurrent (OC)",
            "protection.groups.0.oc",
            self.page.ELEMENT_NAMES,
            0,
        )
        dialog.curve_type.setCurrentText("IEC VI")
        dialog.pickup.setValue(345)
        dialog.close()

        element = self.page._config["protection"]["groups"][0]["oc"]["elements"][0]
        self.assertEqual(element["type"], "IEC VI")
        self.assertEqual(element["pickup_a"], 345)
        pickup_widgets = self.page._bindings[
            "protection.groups.0.oc.elements.0.pickup_a"
        ]
        self.assertTrue(all(widget.value() == 345 for widget in pickup_widgets))

    def test_tcc_dialog_persists_element_enable_state(self) -> None:
        dialog = self.page._open_tcc_dialog(
            "Phase Overcurrent (OC)",
            "protection.groups.0.oc",
            self.page.ELEMENT_NAMES,
            0,
        )
        item = dialog.elements_list.item(0)
        item.setCheckState(Qt.CheckState.Unchecked)
        dialog.close()

        element = self.page._config["protection"]["groups"][0]["oc"]["elements"][0]
        self.assertFalse(element["enabled"])

    def test_highset_exposes_only_company_supported_tcc_fields(self) -> None:
        base = "protection.groups.0.oc.elements.2"

        self.assertFalse(self.page._bindings[f"{base}.type"][0].isEnabled())
        self.assertTrue(self.page._bindings[f"{base}.pickup_a"][0].isEnabled())
        self.assertTrue(self.page._bindings[f"{base}.tripping_time_s"][0].isEnabled())
        self.assertEqual(
            self.page._bindings[f"{base}.tripping_time_s"][0].maximum(), TIME.maximum
        )
        self.assertFalse(self.page._bindings[f"{base}.time_multiplier"][0].isEnabled())
        reset = self.page._bindings[f"{base}.reset_time_s"][0]
        self.assertFalse(reset.isEnabled())
        self.assertEqual(
            reset.buttonSymbols(), QAbstractSpinBox.ButtonSymbols.NoButtons
        )

    def test_ef_reset_time_matches_company_editor_rules(self) -> None:
        base = "protection.groups.0.ef.elements.0"
        curve = self.page._bindings[f"{base}.type"][0]
        reset = self.page._bindings[f"{base}.reset_time_s"][0]

        curve.setCurrentText("TD")
        self.assertTrue(reset.isEnabled())
        self.assertEqual(reset.maximum(), TIME.maximum)
        self.assertEqual(
            reset.buttonSymbols(), QAbstractSpinBox.ButtonSymbols.UpDownArrows
        )
        reset.setValue(1.75)
        self.page.update_config(self.page._config)
        self.assertEqual(
            self.page._config["protection"]["groups"][0]["ef"]["elements"][0][
                "reset_time_s"
            ],
            1.75,
        )

        curve.setCurrentText("ANSI EI")
        self.assertFalse(reset.isEnabled())
        self.assertEqual(
            reset.buttonSymbols(), QAbstractSpinBox.ButtonSymbols.NoButtons
        )

    def test_over_voltage_ranges_do_not_clamp_company_defaults(self) -> None:
        for key in ("ov1", "ov2"):
            widget = self.page._bindings[
                f"protection.groups.0.master.over_voltage.{key}.multiplier"
            ][0]
            self.assertEqual(widget.minimum(), 0.0)
            self.assertEqual(widget.maximum(), 42949672.95 if key == "ov1" else 2.55)

    def test_all_auto_recloser_tcc_editors_stay_inside_their_columns(self) -> None:
        page = ProtectionPage()
        page.set_device_model("FC22AR")
        page.setStyleSheet(V2_STYLE_SHEET + V2_COMPACT_STYLE)
        page.resize(1800, 900)
        page.show()
        self.app.processEvents()
        tables = page.findChildren(QTableWidget, "tccElementTable")
        self.assertEqual(len(tables), 16)

        for table in tables:
            for row in range(table.rowCount()):
                for column in range(table.columnCount()):
                    editor = table.cellWidget(row, column)
                    self.assertIsNotNone(editor)
                    self.assertLessEqual(
                        editor.width(),
                        table.columnWidth(column),
                        f"row {row}, column {column}",
                    )
        page.close()


class GeneralFunctionMenuTests(unittest.TestCase):
    @staticmethod
    def _row_is_visible(form, field) -> bool:
        is_row_visible = getattr(form, "isRowVisible", None)
        return is_row_visible(field) if is_row_visible is not None else not field.isHidden()

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_function_editor_uses_company_choices_and_numeric_point_ids(self) -> None:
        page = GeneralPage()
        config = default_config()
        page.apply_config(config)
        base = "general.system.functions.0"
        point = page._bindings[f"{base}.value_a"][0]
        action = page._bindings[f"{base}.action"][0]
        operator = page._bindings[f"{base}.operator"][0]

        self.assertEqual(
            [action.itemText(index) for index in range(action.count())],
            ["NOTHING", "OPEN", "CLOSE"],
        )
        self.assertEqual(
            [operator.itemText(index) for index in range(operator.count())],
            ["OR", "AND", "EQUAL"],
        )
        self.assertIsInstance(point.itemData(1), int)
        point.setCurrentIndex(1)
        page.update_config(config)
        self.assertEqual(
            config["general"]["system"]["functions"][0]["value_a"],
            point.itemData(1),
        )

    def test_unknown_function_point_id_is_preserved(self) -> None:
        page = GeneralPage()
        config = default_config()
        config["general"]["system"]["functions"][0]["value_a"] = 65535

        page.apply_config(config)
        page.update_config(config)

        self.assertEqual(
            config["general"]["system"]["functions"][0]["value_a"], 65535
        )

    def test_analog_function_shows_only_analog_fields_after_load(self) -> None:
        page = GeneralPage()
        config = default_config()
        function = config["general"]["system"]["functions"][0]
        function["value_type"] = "ANALOG"
        base = "general.system.functions.0"
        binary_operator = page._bindings[f"{base}.operator"][0]
        analog_operator = page._bindings[f"{base}.analog_operator"][0]
        form = binary_operator.parentWidget().layout()

        page.apply_config(config)

        self.assertFalse(self._row_is_visible(form, binary_operator))
        self.assertTrue(self._row_is_visible(form, analog_operator))

    def test_output_point_choices_follow_device_profile(self) -> None:
        page = GeneralPage()
        output = page._bindings["general.io.digital_outputs.0.when"][0]
        page.set_device_model("FC22AR", 50)
        recloser_count = output.count()

        page.set_device_model("FC22S", 50)

        self.assertLess(output.count(), recloser_count)
        self.assertEqual(output.itemData(0), 0)
        self.assertEqual(output.itemText(0), "NOT SELECTED")

    def test_company_numeric_limits_are_exposed_exactly(self) -> None:
        page = GeneralPage()
        validation = page._bindings[
            "general.io.digital_inputs.validation_time_s"
        ][0]
        analog_value = page._bindings[
            "general.system.functions.0.analog_compared_to"
        ][0]
        phase_angle = page._bindings[
            "general.system.synchronization.phase_angle_difference_deg"
        ][0]
        fundamental = page._bindings[
            "general.system.synchronization.fundamental_frequency_hz"
        ][0]

        self.assertEqual((validation.minimum(), validation.maximum()), (0, 0.255))
        self.assertEqual(analog_value.maximum(), 4_294_967_295)
        self.assertIsInstance(phase_angle, QSpinBox)
        self.assertEqual((phase_angle.minimum(), phase_angle.maximum()), (0, 255))
        self.assertIsInstance(fundamental, QSpinBox)
        self.assertEqual((fundamental.minimum(), fundamental.maximum()), (0, 255))
        for transport in ("ethernet", "modem"):
            for port in ("local_port", "remote_port"):
                widget = page._bindings[
                    f"general.scada.ports.{transport}.{port}"
                ][0]
                self.assertEqual((widget.minimum(), widget.maximum()), (0, 65535))
        self.assertEqual(
            page._bindings["general.scada.ports.modem.apn"][0].maxLength(), 15
        )

    def test_ui_load_and_save_is_byte_exact_for_company_defaults(self) -> None:
        for model in ("FC22AR", "FC22S"):
            with self.subTest(model=model):
                payload = default_settings_file(model)[:-3]
                native = decode_settings_payload(payload, model)
                config = default_config()
                update_config_from_native(config, native)
                general = GeneralPage()
                protection = ProtectionPage()
                general.set_device_model(model, 50)
                protection.set_device_model(model)

                general.apply_config(config)
                protection.apply_config(config)
                general.update_config(config)
                protection.update_config(config)
                update_native_from_config(native, config)

                self.assertEqual(
                    patch_settings_payload(payload, native, model), payload
                )


if __name__ == "__main__":
    unittest.main()
