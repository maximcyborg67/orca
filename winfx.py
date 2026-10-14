"""Эффекты окна Windows: размытый «стеклянный» фон и тёмный заголовок."""
import ctypes
from ctypes import wintypes

dwm = ctypes.windll.dwmapi
user32 = ctypes.windll.user32

DWMWA_USE_IMMERSIVE_DARK_MODE = 20


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]


def supports_backdrop():
    return True


def _accent(hwnd, state, color=0, flags=0):
    acc = ACCENT_POLICY()
    acc.AccentState = state
    acc.AccentFlags = flags
    acc.GradientColor = color
    data = WINCOMPATTRDATA()
    data.Attribute = 19                               # WCA_ACCENT_POLICY
    data.Data = ctypes.cast(ctypes.pointer(acc), ctypes.c_void_p)
    data.SizeOfData = ctypes.sizeof(acc)
    return user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data))


def set_caption_colors(hwnd, caption=None, text=None, border=None):
    """Цвет заголовка окна под тему (Windows 11). Цвета — (r, g, b); None — вернуть системный."""
    def rgb(c):
        return 0xFFFFFFFF if c is None else (c[0] | (c[1] << 8) | (c[2] << 16))   # COLORREF; 0xFFFFFFFF = по умолчанию
    try:
        for attr, c in ((35, caption), (36, text), (34, border)):    # CAPTION_COLOR, TEXT_COLOR, BORDER_COLOR
            v = ctypes.c_uint(rgb(c))
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


def set_dark_titlebar(hwnd, dark):
    try:
        v = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


def set_glass(hwnd, on, kind="blur", dark=True):
    """kind: 'blur' — прозрачное размытие (прозрачность задают цвета темы); 'acrylic' — размытие с лёгкой тонировкой.
    Возвращает True, если эффект включён."""
    try:
        set_dark_titlebar(hwnd, dark)
        if not on:
            _accent(hwnd, 0)
            return False
        if kind == "acrylic":
            tint = 0x55141418 if dark else 0x55F4F0F0        # AABBGGRR
            _accent(hwnd, 4, tint, 2)                         # ACCENT_ENABLE_ACRYLICBLURBEHIND
        else:
            _accent(hwnd, 3)                                  # ACCENT_ENABLE_BLURBEHIND
        return True
    except Exception:
        return False
