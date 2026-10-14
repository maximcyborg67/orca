"""Родное контекстное меню Windows (то же, что в обычном Проводнике): «Открыть с помощью», «Отправить»,
архиваторы, антивирус и т.д. Подключаемся к системе напрямую через COM (ctypes).
Наши пункты (вкладки, закладки) добавляются сверху; вырезать/копировать/удалить/переименовать
выполняет сама программа, остальное — Windows."""
import ctypes
from ctypes import wintypes, POINTER, byref, c_void_p, c_uint, c_ulong, c_ushort, c_ubyte, c_wchar_p, c_size_t, c_ssize_t

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication

shell32 = ctypes.windll.shell32
ole32 = ctypes.windll.ole32
user32 = ctypes.windll.user32
HRESULT = ctypes.c_long

shell32.SHParseDisplayName.argtypes = [c_wchar_p, c_void_p, POINTER(c_void_p), c_ulong, POINTER(c_ulong)]
shell32.SHParseDisplayName.restype = HRESULT
shell32.SHBindToParent.argtypes = [c_void_p, c_void_p, POINTER(c_void_p), POINTER(c_void_p)]
shell32.SHBindToParent.restype = HRESULT
ole32.CoTaskMemFree.argtypes = [c_void_p]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.InsertMenuW.argtypes = [wintypes.HMENU, c_uint, c_uint, c_size_t, c_wchar_p]
user32.TrackPopupMenuEx.argtypes = [wintypes.HMENU, c_uint, ctypes.c_int, ctypes.c_int, wintypes.HWND, c_void_p]
user32.TrackPopupMenuEx.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuStringW.argtypes = [wintypes.HMENU, c_uint, c_wchar_p, ctypes.c_int, c_uint]
user32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]

CMF_NORMAL, CMF_EXPLORE, CMF_CANRENAME, CMF_ITEMMENU, CMF_EXTENDEDVERBS = 0, 0x4, 0x10, 0x80, 0x100
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100
MF_BYPOSITION, MF_STRING, MF_SEPARATOR = 0x400, 0x0, 0x800
GCS_VERBW = 4
ID_FIRST, ID_LAST, ID_OURS = 1, 0x7FFF, 0x8001


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort), ("Data4", c_ubyte * 8)]


def _guid(s):
    g = GUID()
    ole32.IIDFromString(s, byref(g))
    return g


IID_IShellFolder = _guid("{000214E6-0000-0000-C000-000000000046}")
IID_IContextMenu = _guid("{000214E4-0000-0000-C000-000000000046}")
IID_IContextMenu2 = _guid("{000214F4-0000-0000-C000-000000000046}")
IID_IContextMenu3 = _guid("{BCFCE0A0-EC17-11D0-8D10-00A0C90F2719}")


def _vcall(p, idx, argtypes, *args, restype=HRESULT):
    vtbl = ctypes.cast(c_void_p(p), POINTER(c_void_p))[0]
    fn = ctypes.cast(c_void_p(vtbl), POINTER(c_void_p))[idx]
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(fn)(p, *args)


def _release(p):
    if p:
        _vcall(p, 2, (), restype=c_ulong)


class CMINVOKECOMMANDINFOEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", wintypes.DWORD), ("hwnd", wintypes.HWND),
        ("lpVerb", c_void_p), ("lpParameters", c_void_p), ("lpDirectory", c_void_p),
        ("nShow", ctypes.c_int), ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
        ("lpTitle", c_void_p), ("lpVerbW", c_void_p), ("lpParametersW", c_void_p),
        ("lpDirectoryW", c_void_p), ("lpTitleW", c_void_p), ("ptInvoke", wintypes.POINT),
    ]


class _Ctx:
    """Системное меню для набора файлов из одной папки."""

    def __init__(self, paths, hwnd):
        self.hwnd = hwnd
        self.pidls = []
        self.psf = c_void_p()
        self.pcm = c_void_p()
        self.pcm2 = None
        self.pcm3 = None
        try:
            self._create(paths)
        except Exception:
            self.close()
            raise

    def _create(self, paths):
        children = []
        for i, path in enumerate(paths):
            pidl = c_void_p()
            hr = shell32.SHParseDisplayName(path, None, byref(pidl), 0, None)
            if hr < 0:
                raise OSError(f"SHParseDisplayName {hr:#x}")
            self.pidls.append(pidl)
            psf = c_void_p()
            last = c_void_p()
            hr = shell32.SHBindToParent(pidl, byref(IID_IShellFolder), byref(psf), byref(last))
            if hr < 0:
                raise OSError(f"SHBindToParent {hr:#x}")
            if i == 0:
                self.psf = psf
            else:
                _release(psf.value)
            children.append(last.value)
        arr = (c_void_p * len(children))(*children)
        hr = _vcall(self.psf.value, 10,
                    (wintypes.HWND, c_uint, c_void_p, c_void_p, c_void_p, c_void_p),
                    self.hwnd, len(children), ctypes.cast(arr, c_void_p), byref(IID_IContextMenu), None,
                    byref(self.pcm))
        if hr < 0 or not self.pcm.value:
            raise OSError(f"GetUIObjectOf {hr:#x}")
        for iid, attr in ((IID_IContextMenu3, "pcm3"), (IID_IContextMenu2, "pcm2")):
            out = c_void_p()
            if _vcall(self.pcm.value, 0, (c_void_p, c_void_p), byref(iid), byref(out)) >= 0 and out.value:
                setattr(self, attr, out)
                break

    def query(self, hmenu, flags):
        return _vcall(self.pcm.value, 3, (wintypes.HMENU, c_uint, c_uint, c_uint, c_uint),
                      hmenu, 0, ID_FIRST, ID_LAST, flags)

    def verb(self, cmd):
        buf = ctypes.create_unicode_buffer(260)
        hr = _vcall(self.pcm.value, 5, (c_size_t, c_uint, c_void_p, c_void_p, c_uint),
                    cmd - ID_FIRST, GCS_VERBW, None, ctypes.cast(buf, c_void_p), 260)
        return buf.value.lower() if hr >= 0 else ""

    def invoke(self, cmd, pt):
        info = CMINVOKECOMMANDINFOEX()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x4000 | 0x20000   # UNICODE | PTINVOKE
        info.hwnd = self.hwnd
        info.lpVerb = cmd - ID_FIRST
        info.lpVerbW = cmd - ID_FIRST
        info.nShow = 1
        info.ptInvoke = pt
        return _vcall(self.pcm.value, 4, (c_void_p,), byref(info))

    def handle_msg(self, msg, wp, lp):
        """Нужно для вложенных меню («Отправить», «Открыть с помощью») — иначе они пустые."""
        if self.pcm3 is not None:
            res = ctypes.c_ssize_t(0)
            _vcall(self.pcm3.value, 7, (c_uint, c_size_t, c_ssize_t, POINTER(ctypes.c_ssize_t)),
                   msg, wp, lp, byref(res))
            return res.value
        if self.pcm2 is not None:
            _vcall(self.pcm2.value, 6, (c_uint, c_size_t, c_ssize_t), msg, wp, lp)
            return 0
        return None

    def close(self):
        for p in (self.pcm3, self.pcm2, self.pcm, self.psf):
            if p is not None and p.value:
                _release(p.value)
        self.pcm3 = self.pcm2 = None
        self.pcm = self.psf = c_void_p()
        for pidl in self.pidls:
            if pidl.value:
                ole32.CoTaskMemFree(pidl.value)
        self.pidls = []


class _Filter(QAbstractNativeEventFilter):
    """Пока меню открыто, передаём ему сообщения окна (рисование пунктов, раскрытие подменю)."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) != b"windows_generic_MSG":
                return False, 0
            msg = wintypes.MSG.from_address(int(message))
            if msg.message in (0x117, 0x2B, 0x2C, 0x120):   # INITMENUPOPUP, DRAWITEM, MEASUREITEM, MENUCHAR
                res = self.ctx.handle_msg(msg.message, msg.wParam, msg.lParam)
                if res is not None:
                    return True, res
        except Exception:
            pass
        return False, 0


def menu_items(hmenu):
    """Список подписей верхнего уровня (для проверок)."""
    out = []
    for i in range(user32.GetMenuItemCount(hmenu)):
        buf = ctypes.create_unicode_buffer(200)
        user32.GetMenuStringW(hmenu, i, buf, 200, MF_BYPOSITION)
        out.append(buf.value)
    return out


def popup(paths, hwnd, extras=(), own_verbs=None, shift=False):
    """Показывает системное меню. extras — [(подпись, функция)], own_verbs — {'copy': функция, ...}.
    Возвращает True, если меню показано (иначе — исключение, можно показать своё)."""
    own_verbs = own_verbs or {}
    ctx = _Ctx(paths, hwnd)
    hmenu = user32.CreatePopupMenu()
    flt = None
    try:
        flags = CMF_NORMAL | CMF_EXPLORE | CMF_CANRENAME | CMF_ITEMMENU | (CMF_EXTENDEDVERBS if shift else 0)
        hr = ctx.query(hmenu, flags)
        if hr < 0:
            raise OSError(f"QueryContextMenu {hr:#x}")
        pos = 0
        for i, (label, _fn) in enumerate(extras):
            user32.InsertMenuW(hmenu, pos, MF_BYPOSITION | MF_STRING, ID_OURS + i, label)
            pos += 1
        if extras:
            user32.InsertMenuW(hmenu, pos, MF_BYPOSITION | MF_SEPARATOR, 0, None)
        pt = wintypes.POINT()
        user32.GetCursorPos(byref(pt))
        user32.SetForegroundWindow(hwnd)
        flt = _Filter(ctx)
        QApplication.instance().installNativeEventFilter(flt)
        try:
            cmd = user32.TrackPopupMenuEx(hmenu, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, hwnd, None)
        finally:
            QApplication.instance().removeNativeEventFilter(flt)
        if cmd >= ID_OURS:
            extras[cmd - ID_OURS][1]()
        elif cmd > 0:
            verb = ctx.verb(cmd)
            fn = own_verbs.get(verb)
            if fn is not None:
                fn()
            else:
                ctx.invoke(cmd, pt)
        return True
    finally:
        user32.DestroyMenu(hmenu)
        ctx.close()
