from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from wolfeye.branding import PRODUCT_NAME
from wolfeye.qt import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QEvent,
    QObject,
    QSettings,
    Qt,
    QTimer,
    QAction,
    QPixmap,
)

from wolfeye.config_schema import default_config
from wolfeye.models import DeviceInfo, MeasurementSnapshot
from wolfeye.services.beacheye import (
    SIGNAL_SAMPLE_RATE_HZ,
    decode_settings_file,
    decode_settings_payload,
    default_settings_file,
    default_settings_json,
    encode_settings_file,
    patch_settings_payload,
    settings_file_from_payload,
)
from wolfeye.services.native_config import (
    update_config_from_native,
    update_native_from_config,
)
from wolfeye.services.device_service import DeviceService
from wolfeye.styles import (
    V2_COMPACT_STYLE,
    V2_EMWOLF_COMPACT_STYLE,
    V2_EMWOLF_STYLE,
    V2_STYLE_SHEET,
    build_v2_style_sheet,
)
from wolfeye.widgets.config_pages import GeneralPage, ProtectionPage
from wolfeye.widgets.emwolf_page import EmWolfPage
from wolfeye.widgets.fc22_tester_page import Fc22TesterPage
from wolfeye.widgets.native_settings import NativeSettingsPage
from wolfeye.widgets.pages import (
    EventsPage,
    MeasurementPage,
    SignalPage,
    StatusPage,
)


def asset_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "assets" / name


def logo(name: str, width: int, height: int) -> QLabel:
    label = QLabel()
    label.setFixedSize(width, height)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pixmap = QPixmap(str(asset_path(name)))
    if not pixmap.isNull():
        label.setPixmap(
            pixmap.scaled(
                width,
                height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    return label


def _scrollable(content: QWidget, *, horizontal_only: bool = False) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        if horizontal_only
        else Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    scroll.setWidget(content)
    return scroll


class _ValueControlWheelGuard(QObject):
    """Require click focus before wheel-changing a combo or numeric input."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            event.type() != QEvent.Type.Wheel
            or not isinstance(watched, (QAbstractSpinBox, QComboBox))
        ):
            return False

        focused = QApplication.focusWidget()
        if watched.hasFocus() or (
            focused is not None and watched.isAncestorOf(focused)
        ):
            return False

        parent = watched.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            QApplication.sendEvent(parent.viewport(), event)
        return True


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(PRODUCT_NAME)
        self.resize(1280, 840)
        self.settings = QSettings()
        self.config = default_config()
        self.service = DeviceService()
        self._raw_legacy_settings: bytes | None = None
        self._native_settings: dict[str, object] | None = None
        self._settings_model = ""
        self._device_busy = False
        self._wheel_guard = _ValueControlWheelGuard(self)
        QApplication.instance().installEventFilter(self._wheel_guard)
        self._build_ui()
        self._configure_appearance()
        self._build_menu()
        self._wire_events()
        self.general_page.apply_config(self.config)
        self.protection_page.apply_config(self.config)
        self._restore_settings()
        self._load_native_defaults()
        self.log(
            f"{PRODUCT_NAME} is ready. Select NATIVE for the current protocol or LEGACY for older TCP/HTTP devices.",
            "info",
        )
        self.log("EmWolf uses the verified EWS2 TCP protocol on port 666.", "info")

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 10, 12, 10)

        self.ip = QLineEdit("192.168.137.10")
        self.ip.setMaximumWidth(160)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("primary")
        self.connection = QLabel("Disconnected")
        self.connection.setObjectName("disconnected")

        self.tabs = QTabWidget()
        self.status_page = StatusPage()
        self.measurement_page = MeasurementPage()
        self.general_page = GeneralPage()
        self.protection_page = ProtectionPage()
        self.native_settings_page = NativeSettingsPage()
        self.signal_page = SignalPage()
        self.events_page = EventsPage()
        self.emwolf_page = EmWolfPage()
        self.fc22_tester_page = Fc22TesterPage()
        self._tab_containers: dict[QWidget, QScrollArea] = {}
        for page, title in (
            (self.status_page, "System Status"),
            (self.measurement_page, "Measurements"),
            (self.general_page, "General"),
            (self.protection_page, "Protection"),
            (self.signal_page, "Signal Viewer"),
            (self.events_page, "Event Viewer"),
            (self.emwolf_page, "EmWolf"),
            (self.fc22_tester_page, "FC22 Tester"),
        ):
            container = _scrollable(page)
            self._tab_containers[page] = container
            self.tabs.addTab(container, title)
        outer.addWidget(self.tabs)

        device_operations = QWidget()
        foot = QHBoxLayout(device_operations)
        foot.setContentsMargins(12, 6, 12, 6)
        foot.addWidget(QLabel("IP"))
        foot.addWidget(self.ip)
        foot.addWidget(self.connect_btn)
        foot.addWidget(self.connection)
        foot.addSpacing(12)
        self.device_summary = QLabel("No device connected")
        self.device_summary.setObjectName("muted")
        foot.addWidget(self.device_summary)
        foot.addStretch()
        foot.addWidget(QLabel("Type"))
        self.device_type = QComboBox()
        self.device_type.addItems(("Recloser", "Sectionalizer"))
        foot.addWidget(self.device_type)
        self.defaults_btn = QPushButton("Load defaults")
        self.read_btn = QPushButton("Read settings")
        self.write_btn = QPushButton("Write settings")
        self.status_btn = QPushButton("Read status")
        self.reset_btn = QPushButton("RESET")
        self.reset_btn.setObjectName("danger")
        foot.addWidget(self.defaults_btn)
        for button in (self.read_btn, self.write_btn, self.status_btn, self.reset_btn):
            button.setEnabled(False)
            foot.addWidget(button)
        self.setCentralWidget(root)

        self.device_operations_dock = QDockWidget("Device operations", self)
        self.device_operations_dock.setObjectName("deviceOperationsDock")
        self.device_operations_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.device_operations_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.device_operations_dock.setWidget(
            _scrollable(device_operations, horizontal_only=True)
        )
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.device_operations_dock
        )

        self.emwolf_log_dock = QDockWidget("EmWolf Log", self)
        self.emwolf_log_dock.setObjectName("emwolfLogDock")
        self.emwolf_log_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.emwolf_log_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.emwolf_log_view = QPlainTextEdit()
        self.emwolf_log_view.setReadOnly(True)
        self.emwolf_log_view.setMaximumBlockCount(1000)
        self.emwolf_log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.emwolf_log_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.emwolf_log_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.emwolf_log_dock.setWidget(self.emwolf_log_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.emwolf_log_dock)
        self.emwolf_log_dock.hide()

        dock = QDockWidget("Messages", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.setMaximumBlockCount(1000)
        dock.setWidget(self.messages)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.setMaximumHeight(180)
        dock.setVisible(False)
        self.statusBar().showMessage("Ready")

    def _configure_appearance(self) -> None:
        self._compact_mode: bool | None = None
        self._screen_hooked = False
        self._resize_timer = QTimer(self)
        self._resize_timer.setInterval(100)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._apply_responsive_layout)
        emwolf_base_style = self.emwolf_page.styleSheet()
        self._install_brand_bar()
        self.setStyleSheet(
            build_v2_style_sheet(asset_path("combo-arrow.svg").parent)
            + V2_COMPACT_STYLE
        )
        self.emwolf_page.setStyleSheet(
            emwolf_base_style + V2_EMWOLF_STYLE + V2_EMWOLF_COMPACT_STYLE
        )
        self._apply_responsive_layout()

    def _install_brand_bar(self) -> None:
        brand = QFrame()
        brand.setObjectName("brandBar")
        brand.setFixedHeight(62)
        row = QHBoxLayout(brand)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(10)
        self.brand_layout = row

        row.addWidget(logo("company.png", 48, 44))

        text = QVBoxLayout()
        text.setSpacing(0)
        title = QLabel(PRODUCT_NAME)
        title.setObjectName("v2Title")
        self.subtitle = QLabel(
            "Protection, measurement and EmWolf engineering console"
        )
        self.subtitle.setObjectName("v2Subtitle")
        text.addWidget(title)
        text.addWidget(self.subtitle)
        row.addLayout(text)
        row.addStretch()

        badge = QLabel("FARTAK CONTROL")
        badge.setObjectName("v2Badge")
        row.addWidget(badge)
        row.addWidget(logo("wolfeye.png", 54, 48))

        self.centralWidget().layout().insertWidget(0, brand)
        self.brand_bar = brand

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_resize_timer"):
            self._resize_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_hooked:
            handle.screenChanged.connect(self._schedule_responsive_layout)
            self._screen_hooked = True

    def _schedule_responsive_layout(self, *_args) -> None:
        self._resize_timer.start()

    def _apply_responsive_layout(self) -> None:
        compact = self.width() < 1600 or self.height() < 900
        if compact == self._compact_mode:
            return
        self._compact_mode = compact
        self.setUpdatesEnabled(False)
        try:
            outer = self.centralWidget().layout()
            outer.setContentsMargins(*(8, 5, 8, 5) if compact else (12, 10, 12, 10))
            outer.setSpacing(5 if compact else 6)
            self.brand_bar.setFixedHeight(56 if compact else 62)
            self.brand_layout.setContentsMargins(
                *(10, 4, 10, 4) if compact else (12, 6, 12, 6)
            )
            self.subtitle.setVisible(not compact)

            page = self.emwolf_page
            page.root_layout.setContentsMargins(
                *(6, 3, 6, 3) if compact else (8, 5, 8, 5)
            )
            page.root_layout.setSpacing(3 if compact else 5)
            page.connection_row.setContentsMargins(
                *(7, 6, 7, 4) if compact else (8, 10, 8, 6)
            )
            page.connection_row.setSpacing(5 if compact else 7)
            page.setup_box.setMaximumHeight(104 if compact else 128)
            page.setup_grid.setContentsMargins(
                *(7, 5, 7, 3) if compact else (8, 7, 8, 4)
            )
            page.setup_grid.setHorizontalSpacing(7 if compact else 8)
            page.setup_grid.setVerticalSpacing(1 if compact else 2)
            page.editor_grid.setContentsMargins(
                *(8, 10, 8, 5) if compact else (10, 14, 10, 8)
            )
            page.editor_grid.setVerticalSpacing(0 if compact else 2)
            page.log_view.setMinimumHeight(42 if compact else 72)
            page.log_view.setMaximumHeight(62 if compact else 100)
            page.log_box.setMaximumHeight(112 if compact else 158)
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        open_action = QAction("Open Setup File", self)
        save_action = QAction("Save Setup File", self)
        save_emwolf_action = QAction("Save EmWolf File", self)
        exit_action = QAction("Close", self)
        open_action.triggered.connect(self.open_config)
        save_action.triggered.connect(lambda: self.save_config(save_as=True))
        save_emwolf_action.triggered.connect(self.emwolf_page._save)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        file_menu.addAction(save_action)
        file_menu.addAction(save_emwolf_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        update_menu = self.menuBar().addMenu("Update")
        firmware = QAction("Firmware", self)
        bootloader = QAction("Bootloader", self)
        firmware.triggered.connect(lambda: self.select_update("Firmware"))
        bootloader.triggered.connect(lambda: self.select_update("Bootloader"))
        update_menu.addAction(firmware)
        update_menu.addSeparator()
        update_menu.addAction(bootloader)

        view_menu = self.menuBar().addMenu("View")
        device_operations_action = self.device_operations_dock.toggleViewAction()
        device_operations_action.setText("Device operations")
        view_menu.addAction(device_operations_action)
        emwolf_log_action = self.emwolf_log_dock.toggleViewAction()
        emwolf_log_action.setText("EmWolf Log")
        view_menu.addAction(emwolf_log_action)

    def _wire_events(self) -> None:
        self.tabs.currentChanged.connect(self._update_device_operations_visibility)
        self._update_device_operations_visibility(self.tabs.currentIndex())
        self.emwolf_page.log_line.connect(self.emwolf_log_view.appendPlainText)
        self.emwolf_page.test_run_started.connect(self.fc22_tester_page.on_emwolf_run_started)
        self.emwolf_page.test_result.connect(self.fc22_tester_page.on_emwolf_result)
        self.emwolf_page.log_window_requested.connect(self._show_emwolf_log_window)
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.status_page.control_requested.connect(self.service.send_control)
        self.status_page.refresh_requested.connect(self.service.refresh)
        self.measurement_page.refresh_requested.connect(self.service.refresh)
        self.events_page.load_requested.connect(self.service.request_events)
        self.signal_page.signal_requested.connect(self.request_signal)
        self.read_btn.clicked.connect(self.read_settings)
        self.write_btn.clicked.connect(self.write_settings)
        self.defaults_btn.clicked.connect(self.load_defaults)
        self.status_btn.clicked.connect(self.service.refresh)
        self.reset_btn.clicked.connect(self.service.reset_device)
        self.device_type.currentTextChanged.connect(self._on_device_type_changed)
        self.service.connection_changed.connect(self.on_connection)
        self.service.connection_changed.connect(self.fc22_tester_page.set_device_info)
        self.service.measurements_changed.connect(self.on_measurements)
        self.service.events_changed.connect(self.events_page.set_events)
        self.service.signal_received.connect(self.on_signal)
        self.service.settings_received.connect(self.on_raw_settings)
        self.service.message.connect(self.log)
        self.service.busy_changed.connect(self.on_busy)
        self.service.update_progress.connect(self.on_update_progress)

    def _on_device_type_changed(self, _text: str) -> None:
        model = self._selected_model()
        self._collect_config()
        self.general_page.set_device_model(model)
        self.protection_page.set_device_model(model)
        self.status_page.set_device_model(model)

        # The original client only changes the device-specific menu here; it
        # does not discard the edited setup.  Rebase the native backing object
        # for the selected model while retaining every shared UI value.
        if self._native_settings is not None and model != self._settings_model:
            native = default_settings_json(model)
            update_native_from_config(native, self.config)
            data = encode_settings_file(native, model)
            self._native_settings = native
            self._raw_legacy_settings = data[:-3]
            self.native_settings_page.set_settings(native)
        self._settings_model = model

    def _update_device_operations_visibility(self, index: int) -> None:
        if self.tabs.widget(index) is self._tab_containers[self.emwolf_page]:
            self.device_operations_dock.hide()
        else:
            self.device_operations_dock.show()

    def _show_emwolf_log_window(self) -> None:
        self.emwolf_log_dock.setFloating(True)
        self.emwolf_log_dock.resize(900, 480)
        self.emwolf_log_dock.show()
        self.emwolf_log_dock.raise_()
        self.emwolf_log_dock.activateWindow()

    def toggle_connection(self) -> None:
        if self.service.connected or self._device_busy:
            self.service.disconnect_device()
        else:
            self.service.connect_device(self.ip.text())

    def on_connection(self, info: DeviceInfo) -> None:
        if info.connected:
            self.connection.setText("Connected")
            self.connection.setObjectName("connected")
            self.connection.setStyleSheet("color:#087f23;font-weight:600")
            self.connect_btn.setText("Disconnect")
            self.device_summary.setText(
                f"{info.model}  |  {info.ip}  |  FW {info.firmware}  HW {info.hardware}  REV {info.build or '-'}  |  {info.transport}"
            )
            self.device_type.setCurrentText(
                "Sectionalizer" if info.model[4:5].upper() == "S" else "Recloser"
            )
            self.general_page.set_device_model(info.model, info.build or 50)
            self.status_page.set_device_model(info.model)
        else:
            self.connection.setText("Disconnected")
            self.connection.setObjectName("disconnected")
            self.connection.setStyleSheet("color:#a00000;font-weight:600")
            self.connect_btn.setText("Connect")
            self.device_summary.setText("No device connected")
        for button in (self.read_btn, self.write_btn, self.status_btn, self.reset_btn):
            button.setEnabled(info.connected)
        tcp_available = info.connected and info.transport != "LEGACY HTTP"
        self.measurement_page.set_connected(info.connected)
        self.signal_page.set_available(tcp_available)
        self.events_page.set_available(tcp_available)
        self.status_page.set_device(info)
        self.emwolf_page.set_device_info(info)

    def on_measurements(self, snapshot: MeasurementSnapshot) -> None:
        self.status_page.set_measurements(snapshot)
        self.measurement_page.update_snapshot(snapshot)
        self.fc22_tester_page.on_measurements(snapshot)
        self.statusBar().showMessage(
            f"Measurements updated at {snapshot.timestamp:%H:%M:%S}"
        )

    def on_busy(self, busy: bool) -> None:
        self._device_busy = busy
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText(
            "Stop"
            if busy
            else "Disconnect"
            if self.service.connected
            else "Connect"
        )
        for button in (self.read_btn, self.write_btn, self.status_btn, self.reset_btn):
            button.setEnabled(self.service.connected and not busy)
        tcp_available = (
            self.service.connected
            and self.service.info.transport != "LEGACY HTTP"
            and not busy
        )
        self.measurement_page.set_connected(self.service.connected and not busy)
        self.signal_page.set_available(tcp_available)
        self.events_page.set_available(tcp_available)

    def read_settings(self) -> None:
        self.service.read_settings()

    def write_settings(self) -> None:
        if self._native_settings is None:
            self.log(
                "Read settings from the device or open an FC22 setup before writing.",
                "warning",
            )
            return
        if (
            self._settings_model
            and self.service.info.model in {"FC22AR", "FC22S"}
            and self._settings_model != self.service.info.model
        ):
            self.log(
                f"Settings are for {self._settings_model}, but the connected device is {self.service.info.model}.",
                "error",
            )
            return
        try:
            self._collect_config()
            self._native_settings = self.native_settings_page.settings()
            update_native_from_config(self._native_settings, self.config)
            self.native_settings_page.set_settings(self._native_settings)
            model = self._settings_model or self._selected_model()
            self._raw_legacy_settings = patch_settings_payload(
                self._raw_legacy_settings, self._native_settings, model
            )
        except (TypeError, ValueError) as exc:
            self.log(f"Company settings contain an invalid value: {exc}", "error")
            return
        self.service.write_settings(self._raw_legacy_settings)

    def request_signal(self) -> None:
        self._collect_config()
        self.service.request_signal()

    def on_signal(self, channels: list[list[float]]) -> None:
        frequency = (
            self.config.get("general", {}).get("measurement", {}).get("frequency_hz")
        )
        try:
            rated_frequency = float(frequency)
        except (TypeError, ValueError):
            rated_frequency = None
        self.signal_page.set_samples(
            channels,
            sample_rate_hz=SIGNAL_SAMPLE_RATE_HZ,
            rated_frequency_hz=rated_frequency,
            config=self.config,
        )

    def on_raw_settings(self, payload: bytes) -> None:
        model = self.service.info.model or self._selected_model()
        try:
            self._native_settings = decode_settings_payload(payload, model)
            self._raw_legacy_settings = payload
            self._settings_model = model
            self.native_settings_page.set_settings(self._native_settings)
            update_config_from_native(self.config, self._native_settings)
            self.general_page.set_device_model(model, self.service.info.build or 50)
            self.general_page.apply_config(self.config)
            self.protection_page.set_device_model(model)
            self.protection_page.apply_config(self.config)
            self.status_page.set_device_model(model)
            if len(payload) == 4108:
                self.log(
                    "Received revision 50 settings; raw bytes are preserved for exact backup and write-back.",
                    "success",
                )
            else:
                self.log(
                    f"Received and decoded {len(payload):,} setting bytes with the company Settings ABI.",
                    "success",
                )
        except ValueError as exc:
            self.log(f"Settings were rejected: {exc}", "error")

    def _collect_config(self) -> None:
        self.general_page.update_config(self.config)
        self.protection_page.update_config(self.config)

    def open_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open FC22 setup",
            "",
            "FC22 Setup (*.bin);;All files (*)",
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
            self._native_settings, self._settings_model = decode_settings_file(data)
            self._raw_legacy_settings = data[:-3]
            self.native_settings_page.set_settings(self._native_settings)
            update_config_from_native(self.config, self._native_settings)
            self.general_page.set_device_model(self._settings_model)
            self.general_page.apply_config(self.config)
            self.protection_page.set_device_model(self._settings_model)
            self.protection_page.apply_config(self.config)
            self.status_page.set_device_model(self._settings_model)
            blocked = self.device_type.blockSignals(True)
            self.device_type.setCurrentText(
                "Sectionalizer" if self._settings_model.endswith("S") else "Recloser"
            )
            self.device_type.blockSignals(blocked)
            self.settings.setValue("last_config", path)
            self.log(f"FC22 setup loaded: {path}", "success")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Open failed", str(exc))

    def save_config(self, save_as: bool = False) -> None:
        path = "" if save_as else self.settings.value("last_config", "", str)
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save FC22 setup",
                "DEVolf-setup.bin",
                "FC22 Setup (*.bin);;All files (*)",
            )
        if not path:
            return
        try:
            if Path(path).suffix.lower() != ".bin":
                path += ".bin"
            model = self._settings_model or self._selected_model()
            self._collect_config()
            native = (
                self.native_settings_page.settings()
                if self._native_settings is not None
                else default_settings_json(model)
            )
            update_native_from_config(native, self.config)
            if self._raw_legacy_settings is not None:
                self._raw_legacy_settings = patch_settings_payload(
                    self._raw_legacy_settings, native, model
                )
                data = settings_file_from_payload(self._raw_legacy_settings, model)
            else:
                data = encode_settings_file(native, model)
            self._native_settings = native
            self._raw_legacy_settings = data[:-3]
            Path(path).write_bytes(data)
            self.settings.setValue("last_config", path)
            self.log(
                f"FC22 setup saved: {path} ({len(data):,} bytes)",
                "success",
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def load_defaults(self) -> None:
        self.config = default_config()
        self.general_page.set_device_model(self._selected_model())
        self.general_page.apply_config(self.config)
        self.protection_page.set_device_model(self._selected_model())
        self.protection_page.apply_config(self.config)
        self.status_page.set_device_model(self._selected_model())
        self._load_native_defaults()
        self.log("Default configuration restored.", "info")

    def _selected_model(self) -> str:
        return (
            "FC22S"
            if self.device_type.currentText() == "Sectionalizer"
            else "FC22AR"
        )

    def _load_native_defaults(self) -> None:
        self._settings_model = self._selected_model()
        self.general_page.set_device_model(self._settings_model)
        self.protection_page.set_device_model(self._settings_model)
        self.status_page.set_device_model(self._settings_model)
        data = default_settings_file(self._settings_model)
        self._native_settings, _model = decode_settings_file(data)
        self._raw_legacy_settings = data[:-3]
        self.native_settings_page.set_settings(self._native_settings)
        update_config_from_native(self.config, self._native_settings)
        self.general_page.apply_config(self.config)
        self.protection_page.apply_config(self.config)

    def on_update_progress(self, percent: int, kind: str) -> None:
        self.statusBar().showMessage(f"{kind} upload: {percent}%")
        if percent in {0, 100}:
            self.log(f"{kind} upload: {percent}%", "info")

    def select_update(self, kind: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {kind}", "", "Binary image (*.bin);;All files (*)"
        )
        if path:
            self.service.update_file(kind, path)

    def log(self, text: str, level: str = "info") -> None:
        colors = {
            "success": "#56d694",
            "warning": "#ffbd66",
            "error": "#ff7185",
            "info": "#9cabc0",
        }
        stamp = datetime.now().strftime("%H:%M:%S")
        self.messages.appendHtml(
            f'<span style="color:#66768c">{stamp}</span> <span style="color:{colors.get(level, colors["info"])}">{text}</span>'
        )
        self.statusBar().showMessage(text, 6000)

    def _restore_settings(self) -> None:
        saved_ip = self.settings.value("device_ip", "192.168.137.10", str)
        self.ip.setText("192.168.137.10" if saved_ip == "192.168.137.100" else saved_ip)
        self.device_type.setCurrentText(
            self.settings.value("device_type", "Recloser", str)
        )
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event) -> None:
        self.settings.setValue("device_ip", self.ip.text())
        self.settings.setValue("device_type", self.device_type.currentText())
        self.settings.remove("connection_mode")
        self.settings.setValue("geometry", self.saveGeometry())
        self.emwolf_page.shutdown()
        self.fc22_tester_page.shutdown()
        self.service.disconnect_device()
        event.accept()
