"""Поиск через Everything (voidtools): мгновенный поиск по всем дискам по базе MFT.
Связь — прямая (сообщения Windows WM_COPYDATA), никаких dll и es.exe не нужно. Everything должна быть установлена;
если её окно не запущено, Orca сама стартует «Everything.exe -startup» в фоне."""
import ctypes
import os
import struct
import subprocess
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_COPYDATA = 0x4A
WM_USER = 0x400
IPC_CLASS = "EVERYTHING_TASKBAR_NOTIFICATION"
COPYDATA_QUERY2W = 18
REQ_FULL_PATH, REQ_SIZE, REQ_DATE_MODIFIED = 0x4, 0x10, 0x40
FLAG_FOLDER, FLAG_DRIVE = 0x1, 0x2
SORT = {"name": 1, "name_desc": 2, "path": 3, "path_desc": 4, "size": 5, "size_desc": 6, "date": 13, "date_desc": 14}
MATCH_CASE, MATCH_WHOLE, MATCH_PATH, MATCH_REGEX = 1, 2, 4, 8


class COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wintypes.DWORD), ("lpData", ctypes.c_void_p)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM

_state = {"cls": False, "result": None, "proc": None}
_CLS = "OrcaEverythingReply"


def _proc(hwnd, msg, wp, lp):
    if msg == WM_COPYDATA:
        cds = ctypes.cast(lp, ctypes.POINTER(COPYDATASTRUCT)).contents
        if cds.dwData == 1 and cds.lpData:
            _state["result"] = ctypes.string_at(cds.lpData, cds.cbData)
        return 1
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


def _register():
    if _state["cls"]:
        return
    _state["proc"] = WNDPROC(_proc)                    # держим ссылку, иначе функцию уберёт сборщик мусора
    wc = WNDCLASSW()
    wc.lpfnWndProc = _state["proc"]
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = _CLS
    user32.RegisterClassW(ctypes.byref(wc))
    _state["cls"] = True


def find_window():
    return user32.FindWindowW(IPC_CLASS, None) or None


def exe_path():
    for p in (os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Everything", "Everything.exe"),
              os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Everything", "Everything.exe"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Everything", "Everything.exe")):
        if os.path.isfile(p):
            return p
    return None


def installed():
    return exe_path() is not None or find_window() is not None


def db_loaded(hwnd=None):
    hwnd = hwnd or find_window()
    if not hwnd:
        return False
    return bool(user32.SendMessageW(hwnd, WM_USER, 401, 0))     # EVERYTHING_IPC_IS_DB_LOADED


def ensure_running(timeout=12.0):
    """Окно Everything, готовое отвечать, или None. При необходимости запускает её в фоне."""
    hwnd = find_window()
    if not hwnd:
        p = exe_path()
        if not p:
            return None
        try:
            subprocess.Popen([p, "-startup"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            return None
    t0 = time.time()
    while time.time() - t0 < timeout:
        hwnd = find_window()
        if hwnd and db_loaded(hwnd):
            return hwnd
        time.sleep(0.15)
    return find_window()


def _filetime(v):
    return 0.0 if v <= 0 else (v - 116444736000000000) / 10_000_000


def query(text, offset=0, count=500, sort="name", flags=0, hwnd=None, timeout=15.0):
    """(всего найдено, [(полный_путь, это_папка, размер, время_изменения), …]). None — Everything недоступна."""
    hwnd = hwnd or find_window()
    if not hwnd:
        return None
    _register()
    me = user32.CreateWindowExW(0, _CLS, "orca", 0, 0, 0, 0, 0, wintypes.HWND(-3), None,
                                kernel32.GetModuleHandleW(None), None)       # окно только для сообщений
    if not me:
        return None
    try:
        try:
            user32.ChangeWindowMessageFilterEx(me, WM_COPYDATA, 1, None)      # на случай, если Everything запущена «от админа»
        except Exception:
            pass
        req = REQ_FULL_PATH | REQ_SIZE | REQ_DATE_MODIFIED
        head = struct.pack("<7I", me & 0xFFFFFFFF, 1, flags, offset, count, req, SORT.get(sort, 1))
        data = head + (text + "\0").encode("utf-16-le")
        buf = ctypes.create_string_buffer(data, len(data))
        cds = COPYDATASTRUCT(COPYDATA_QUERY2W, len(data), ctypes.cast(buf, ctypes.c_void_p))
        _state["result"] = None
        ok = user32.SendMessageW(hwnd, WM_COPYDATA, me, ctypes.addressof(cds))
        if not ok:
            return None
        # Everything отвечает чуть позже отдельным сообщением — прокачиваем очередь сообщений, пока оно не придёт
        msg = wintypes.MSG()
        t0 = time.time()
        while _state["result"] is None and time.time() - t0 < timeout:
            # забираем сообщения только нашего скрытого окна (чужие, окна Qt, не трогаем — иначе перезапуск обработчиков);
            # ответ Everything приходит как «посланное» сообщение и обрабатывается внутри самого PeekMessage
            while user32.PeekMessageW(ctypes.byref(msg), me, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if _state["result"] is None:
                time.sleep(0.002)
        blob = _state["result"]
        if not blob:
            return None
    finally:
        user32.DestroyWindow(me)
    totitems, numitems, off, reqf, sortt = struct.unpack_from("<5I", blob, 0)       # EVERYTHING_IPC_LIST2
    items = []
    base = 20
    for i in range(numitems):
        fl, data_off = struct.unpack_from("<II", blob, base + i * 8)
        p = data_off
        # порядок полей в ответе: полный путь, размер, дата изменения
        ln = struct.unpack_from("<I", blob, p)[0]
        p += 4
        name = blob[p:p + ln * 2].decode("utf-16-le", "replace")
        p += (ln + 1) * 2
        size = struct.unpack_from("<q", blob, p)[0]
        p += 8
        mt = struct.unpack_from("<q", blob, p)[0]
        items.append((name, bool(fl & (FLAG_FOLDER | FLAG_DRIVE)), max(0, size), _filetime(mt)))
    return totitems, items
