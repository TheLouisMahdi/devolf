from __future__ import annotations

import atexit
import ctypes
import sys
from pathlib import Path

_window_icons: list[int] = []


def configure_app_user_model_id(app_id: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def force_window_icon(window_id: int, icon_path: str | Path) -> bool:
    """Set both native WM_SETICON sizes so the Windows taskbar uses our icon."""
    if sys.platform != "win32":
        return False
    path = str(Path(icon_path).resolve())
    if not Path(path).is_file():
        return False

    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.LoadImageW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    )
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.SendMessageW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_void_p,
    )

    image_icon = 1
    load_from_file = 0x0010
    wm_seticon = 0x0080
    sizes = (
        (1, user32.GetSystemMetrics(11), user32.GetSystemMetrics(12)),
        (0, user32.GetSystemMetrics(49), user32.GetSystemMetrics(50)),
    )
    loaded: list[int] = []
    for icon_kind, width, height in sizes:
        handle = user32.LoadImageW(
            None, path, image_icon, width, height, load_from_file
        )
        if handle:
            user32.SendMessageW(
                ctypes.c_void_p(window_id),
                wm_seticon,
                icon_kind,
                ctypes.c_void_p(handle),
            )
            loaded.append(int(handle))
    _window_icons.extend(loaded)
    return len(loaded) == 2


def release_window_icons() -> None:
    if sys.platform != "win32":
        return
    while _window_icons:
        ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(_window_icons.pop()))


atexit.register(release_window_icons)
