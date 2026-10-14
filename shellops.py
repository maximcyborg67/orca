"""Настоящие операции Windows с файлами: копирование, перенос, корзина, свойства.

Используется тот же системный механизм (SHFileOperation), что и в обычном Проводнике:
окно прогресса, вопросы про одинаковые имена, корзина — всё родное.
"""
import ctypes
import os
import subprocess
from ctypes import wintypes

from PySide6.QtCore import QThread, Signal

FO_MOVE, FO_COPY, FO_DELETE = 1, 2, 3
FOF_RENAMEONCOLLISION = 0x0008
FOF_ALLOWUNDO = 0x0040          # удалять в корзину
FOF_SILENT_NOCONFIRM = 0x0414   # без окон (только для проверок)


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_void_p),
        ("pTo", ctypes.c_void_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def _multi(paths):
    return ctypes.create_unicode_buffer("\0".join(paths) + "\0\0")


def shell_op(func, srcs, dst=None, flags=0, hwnd=0):
    """Возвращает True, если всё выполнено и пользователь не нажал «Отмена»."""
    fro = _multi(srcs)
    to = _multi([dst]) if dst else None
    op = SHFILEOPSTRUCTW()
    op.hwnd = hwnd
    op.wFunc = func
    op.pFrom = ctypes.cast(fro, ctypes.c_void_p)
    op.pTo = ctypes.cast(to, ctypes.c_void_p) if to is not None else None
    op.fFlags = flags
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc == 0 and not op.fAnyOperationsAborted


class OpWorker(QThread):
    """Выполняет операцию в отдельном потоке, чтобы окно не зависало."""

    def __init__(self, func, srcs, dst, flags, hwnd):
        super().__init__()
        self.args = (func, srcs, dst, flags, hwnd)
        self.ok = False

    def run(self):
        ctypes.windll.ole32.CoInitialize(None)
        try:
            self.ok = shell_op(*self.args)
        except Exception:
            self.ok = False
        finally:
            ctypes.windll.ole32.CoUninitialize()


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def properties(path):
    """Окно «Свойства» Windows."""
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x0000000C   # SEE_MASK_INVOKEIDLIST
    info.lpVerb = "properties"
    info.lpFile = path
    info.nShow = 1
    ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info))


def open_with(path):
    """Окно «Открыть с помощью…»."""
    ctypes.windll.shell32.ShellExecuteW(None, "openas", path, None, None, 1)


def open_file(path):
    os.startfile(path)


def open_terminal(folder):
    try:
        subprocess.Popen(["wt.exe", "-d", folder])
    except OSError:
        subprocess.Popen(["powershell.exe", "-NoExit"], cwd=folder,
                         creationflags=subprocess.CREATE_NEW_CONSOLE)


def reveal(path):
    """Показать файл в обычном Проводнике Windows."""
    subprocess.Popen(["explorer.exe", "/select,", path])
