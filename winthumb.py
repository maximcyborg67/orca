"""Миниатюры средствами Windows (те же, что в обычном Проводнике): видео, PDF, обложки музыки и т.д."""
import ctypes
from ctypes import wintypes

from PySide6.QtGui import QImage

shell32 = ctypes.windll.shell32
gdi32 = ctypes.windll.gdi32
user32 = ctypes.windll.user32
ole32 = ctypes.windll.ole32

SIIGBF_BIGGERSIZEOK = 0x1
SIIGBF_THUMBNAILONLY = 0x8


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                ("bmWidthBytes", ctypes.c_long), ("bmPlanes", ctypes.c_ushort), ("bmBitsPixel", ctypes.c_ushort),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


shell32.SHCreateItemFromParsingName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_void_p)]
shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_uint]
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

_IID = GUID()
ole32.IIDFromString("{BCC18B79-BA16-442F-80C4-8A59C30C463B}", ctypes.byref(_IID))   # IShellItemImageFactory


def _vcall(p, idx, restype, argtypes, *args):
    vtbl = ctypes.cast(ctypes.c_void_p(p), ctypes.POINTER(ctypes.c_void_p))[0]
    fn = ctypes.cast(ctypes.c_void_p(vtbl), ctypes.POINTER(ctypes.c_void_p))[idx]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(fn)(p, *args)


def _hbitmap_to_qimage(hbm):
    bm = BITMAP()
    gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm))
    w, h = bm.bmWidth, bm.bmHeight
    if w <= 0 or h <= 0:
        return QImage()
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(bmi)
    bmi.biWidth = w
    bmi.biHeight = -h           # сверху вниз
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = user32.GetDC(None)
    try:
        gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(bmi), 0)
    finally:
        user32.ReleaseDC(None, hdc)
    raw = bytes(buf)
    has_alpha = any(raw[3::4][:: max(1, len(raw) // 4000)])
    fmt = QImage.Format_ARGB32_Premultiplied if has_alpha else QImage.Format_RGB32
    return QImage(raw, w, h, w * 4, fmt).copy()


def shell_icon(path, size=128):
    """QImage со значком файла (как в Проводнике: у программ — свой, у документов — по типу)."""
    return shell_thumbnail(path, size, SIIGBF_BIGGERSIZEOK | 0x4)   # 0x4 = только значок


def shell_thumbnail(path, size=192, flags=SIIGBF_BIGGERSIZEOK | SIIGBF_THUMBNAILONLY):
    """QImage с миниатюрой от Windows или пустой QImage, если у файла её нет. Вызывать в потоке с CoInitialize."""
    item = ctypes.c_void_p()
    hr = shell32.SHCreateItemFromParsingName(path, None, ctypes.byref(_IID), ctypes.byref(item))
    if hr < 0 or not item.value:
        return QImage()
    hbm = wintypes.HANDLE()
    try:
        hr = _vcall(item.value, 3, ctypes.c_long, (SIZE, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)),
                    SIZE(size, size), flags, ctypes.byref(hbm))
        if hr < 0 or not hbm.value:
            return QImage()
        try:
            return _hbitmap_to_qimage(hbm.value)
        finally:
            gdi32.DeleteObject(hbm.value)
    finally:
        _vcall(item.value, 2, ctypes.c_ulong, ())
