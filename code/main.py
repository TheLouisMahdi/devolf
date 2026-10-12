from __future__ import annotations

import sys
from pathlib import Path

from wolfeye.branding import ORGANIZATION_NAME, PRODUCT_NAME, WINDOWS_APP_ID
from wolfeye.qt import (
    QApplication,
    QIcon,
    QStyleFactory,
    QTimer,
    configure_high_dpi,
)
from wolfeye.services.windows_shell import (
    configure_app_user_model_id,
    force_window_icon,
)
from wolfeye.widgets.main_window import MainWindow


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative


def main() -> int:
    configure_app_user_model_id(WINDOWS_APP_ID)
    configure_high_dpi()
    app = QApplication(sys.argv)
    fixed_style = QStyleFactory.create("Fusion")
    if fixed_style is not None:
        app.setStyle(fixed_style)
    app.setApplicationName(PRODUCT_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)

    icon_path = resource_path("assets/wolfeye.ico")
    app_icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.showMaximized()
    if not app_icon.isNull():
        QTimer.singleShot(0, lambda: force_window_icon(int(window.winId()), icon_path))

    if "--smoke-test" in sys.argv:
        QTimer.singleShot(1200, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
