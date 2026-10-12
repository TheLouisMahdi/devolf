"""Windows GDI/Winspool PDF printing for the FC22 Tester report.

Verbatim port of the validated prototype ``windows_pdf_printer.py``; the
tester report view sends the generated checklist to the Windows default
printer at 300 DPI. Nothing here touches device connections.
"""

from __future__ import annotations

import ctypes
import struct
import sys
from ctypes import wintypes
from pathlib import Path

import pymupdf as fitz


class PrintError(RuntimeError):
    """Raised when a PDF cannot be sent to the Windows default printer."""


def fit_size(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int, int, int]:
    if min(src_w, src_h, dst_w, dst_h) <= 0:
        raise ValueError("Source and destination dimensions must be positive.")
    scale = min(dst_w / src_w, dst_h / src_h)
    width = max(1, int(round(src_w * scale)))
    height = max(1, int(round(src_h * scale)))
    x = (dst_w - width) // 2
    y = (dst_h - height) // 2
    return x, y, width, height


def should_rotate(page_w: float, page_h: float, target_w: int, target_h: int) -> bool:
    page_landscape = page_w > page_h
    target_landscape = target_w > target_h
    return page_landscape != target_landscape


def _windows_api():
    if not sys.platform.startswith("win"):
        raise PrintError("Direct PDF printing is available on Windows only.")

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    winspool.GetDefaultPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    winspool.GetDefaultPrinterW.restype = wintypes.BOOL

    gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
    gdi32.CreateDCW.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    gdi32.StartDocW.argtypes = [wintypes.HDC, ctypes.c_void_p]
    gdi32.StartDocW.restype = ctypes.c_int
    gdi32.EndDoc.argtypes = [wintypes.HDC]
    gdi32.EndDoc.restype = ctypes.c_int
    gdi32.AbortDoc.argtypes = [wintypes.HDC]
    gdi32.AbortDoc.restype = ctypes.c_int
    gdi32.StartPage.argtypes = [wintypes.HDC]
    gdi32.StartPage.restype = ctypes.c_int
    gdi32.EndPage.argtypes = [wintypes.HDC]
    gdi32.EndPage.restype = ctypes.c_int
    gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetStretchBltMode.restype = ctypes.c_int
    gdi32.StretchDIBits.argtypes = [
        wintypes.HDC,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.DWORD,
    ]
    gdi32.StretchDIBits.restype = ctypes.c_int
    return winspool, gdi32


def get_default_printer_name() -> str:
    winspool, _ = _windows_api()
    needed = wintypes.DWORD(0)
    winspool.GetDefaultPrinterW(None, ctypes.byref(needed))
    if needed.value <= 1:
        raise PrintError("No Windows default printer is configured.")
    buf = ctypes.create_unicode_buffer(needed.value)
    if not winspool.GetDefaultPrinterW(buf, ctypes.byref(needed)):
        code = ctypes.get_last_error()
        raise PrintError(f"Windows could not read the default printer (error {code}).")
    name = buf.value.strip()
    if not name:
        raise PrintError("No Windows default printer is configured.")
    return name


class _DOCINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_int),
        ("lpszDocName", wintypes.LPCWSTR),
        ("lpszOutput", wintypes.LPCWSTR),
        ("lpszDatatype", wintypes.LPCWSTR),
        ("fwType", wintypes.DWORD),
    ]


def _check(result: int, action: str) -> int:
    if result <= 0:
        code = ctypes.get_last_error()
        raise PrintError(f"Windows printer error during {action} (error {code}).")
    return result


def _render_bmp(page: fitz.Page, dpi: int, rotate: bool) -> bytes:
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    if rotate:
        matrix = matrix.prerotate(90)
    pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
    return pix.pil_tobytes(format="BMP")


def print_pdf_to_default_printer(pdf_path: str | Path, *, dpi: int = 300) -> str:
    path = Path(pdf_path).expanduser().resolve()
    if not path.is_file():
        raise PrintError(f"PDF file not found: {path}")
    if dpi < 96 or dpi > 600:
        raise ValueError("dpi must be between 96 and 600")

    _, gdi32 = _windows_api()
    printer_name = get_default_printer_name()

    hdc = gdi32.CreateDCW("WINSPOOL", printer_name, None, None)
    if not hdc:
        code = ctypes.get_last_error()
        raise PrintError(f"Could not open printer '{printer_name}' (error {code}).")

    HORZRES = 8
    VERTRES = 10
    HALFTONE = 4
    DIB_RGB_COLORS = 0
    SRCCOPY = 0x00CC0020

    started = False
    doc = None
    try:
        target_w = gdi32.GetDeviceCaps(hdc, HORZRES)
        target_h = gdi32.GetDeviceCaps(hdc, VERTRES)
        if target_w <= 0 or target_h <= 0:
            raise PrintError("The default printer did not report a printable page size.")

        info = _DOCINFOW(
            cbSize=ctypes.sizeof(_DOCINFOW),
            lpszDocName=f"FC22 Form - {path.name}",
            lpszOutput=None,
            lpszDatatype=None,
            fwType=0,
        )
        _check(gdi32.StartDocW(hdc, ctypes.byref(info)), "StartDoc")
        started = True
        gdi32.SetStretchBltMode(hdc, HALFTONE)

        doc = fitz.open(path)
        if len(doc) == 0:
            raise PrintError("The generated PDF contains no pages.")

        for page in doc:
            rotate = should_rotate(page.rect.width, page.rect.height, target_w, target_h)
            bmp = _render_bmp(page, dpi, rotate)
            if len(bmp) < 54 or bmp[:2] != b"BM":
                raise PrintError("Could not rasterize the PDF page for Windows printing.")

            pixel_offset = struct.unpack_from("<I", bmp, 10)[0]
            width = abs(struct.unpack_from("<i", bmp, 18)[0])
            height = abs(struct.unpack_from("<i", bmp, 22)[0])
            if pixel_offset <= 14 or pixel_offset >= len(bmp) or width <= 0 or height <= 0:
                raise PrintError("Invalid rasterized page data.")

            x, y, out_w, out_h = fit_size(width, height, target_w, target_h)
            _check(gdi32.StartPage(hdc), "StartPage")
            raw = ctypes.create_string_buffer(bmp)
            bmi_ptr = ctypes.cast(ctypes.byref(raw, 14), ctypes.c_void_p)
            bits_ptr = ctypes.cast(ctypes.byref(raw, pixel_offset), ctypes.c_void_p)
            result = gdi32.StretchDIBits(
                hdc,
                x, y, out_w, out_h,
                0, 0, width, height,
                bits_ptr, bmi_ptr, DIB_RGB_COLORS, SRCCOPY,
            )
            if result in (0, -1):
                code = ctypes.get_last_error()
                raise PrintError(f"Windows could not draw the PDF page to the printer (error {code}).")
            _check(gdi32.EndPage(hdc), "EndPage")

        _check(gdi32.EndDoc(hdc), "EndDoc")
        started = False
        return printer_name
    except Exception:
        if started:
            gdi32.AbortDoc(hdc)
        raise
    finally:
        if doc is not None:
            doc.close()
        gdi32.DeleteDC(hdc)
