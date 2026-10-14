"""Окно «Свойства» в стиле Orca: тип, место, размер (для папок считается в фоне), даты, атрибуты.
Системное окно Windows (вкладки «Безопасность», «Предыдущие версии») доступно кнопкой внизу."""
import ctypes
import os
import shutil
import time

from PySide6.QtCore import Qt, QFileInfo, QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileIconProvider, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

import shellops as sh
from util import fmt_size, plural

FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_HIDDEN = 0x2
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря")


def fmt_date(ts):
    """14 октября 2026 г., 16:59:14"""
    try:
        t = time.localtime(ts)
    except (OSError, OverflowError, ValueError):
        return "—"
    return f"{t.tm_mday} {MONTHS[t.tm_mon - 1]} {t.tm_year} г., {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"


def fmt_bytes(n):
    """3,02 МБ (3 176 224 байт)"""
    exact = f"{n:,}".replace(",", " ") + " байт"
    return f"{fmt_size(n)} ({exact})" if n >= 1024 else exact


def get_attrs(path):
    a = ctypes.windll.kernel32.GetFileAttributesW(path)
    return 0 if a == 0xFFFFFFFF else a


def set_attr(path, flag, on):
    """Включить или выключить один атрибут. True, если получилось."""
    a = get_attrs(path)
    if a == 0:
        return False
    a = (a | flag) if on else (a & ~flag)
    return bool(ctypes.windll.kernel32.SetFileAttributesW(path, a))


def size_on_disk(path):
    """Сколько файл реально занимает на диске (с учётом кластеров и сжатия). None, если не узнать."""
    hi = ctypes.c_ulong(0)
    k = ctypes.windll.kernel32
    k.GetCompressedFileSizeW.restype = ctypes.c_ulong
    lo = k.GetCompressedFileSizeW(path, ctypes.byref(hi))
    if lo == 0xFFFFFFFF and ctypes.GetLastError() != 0:
        return None
    n = (hi.value << 32) + lo
    cl = _cluster(path)
    return -(-n // cl) * cl if cl and n else n          # округляем вверх до целого кластера, как это делает Windows


_CLUSTERS = {}


def _cluster(path):
    root = os.path.splitdrive(os.path.abspath(path))[0].upper() + "\\"
    if root not in _CLUSTERS:
        spc, bps, a, b = (ctypes.c_ulong() for _ in range(4))
        ok = ctypes.windll.kernel32.GetDiskFreeSpaceW(root, ctypes.byref(spc), ctypes.byref(bps), ctypes.byref(a), ctypes.byref(b))
        _CLUSTERS[root] = spc.value * bps.value if ok else 0
    return _CLUSTERS[root]


class SizeWorker(QThread):
    """Считает размер и число вложенного в фоне; можно остановить, когда окно закрыли."""
    done = Signal(int, int, int, int)           # размер, на диске, файлов, папок

    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self._stop = False

    def cancel(self):
        self._stop = True

    def run(self):
        total = disk = files = dirs = 0
        stack = []
        for p in self.paths:
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    stack.append(p)
                else:
                    total += os.path.getsize(p)
                    disk += size_on_disk(p) or 0
                    files += 1
            except OSError:
                pass
        while stack and not self._stop:
            cur = stack.pop()
            try:
                it = os.scandir(cur)
            except OSError:
                continue
            with it:
                for e in it:
                    if self._stop:
                        break
                    try:
                        if e.is_dir(follow_symlinks=False):
                            dirs += 1
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                            disk += size_on_disk(e.path) or 0
                            files += 1
                    except OSError:
                        continue
        if not self._stop:
            self.done.emit(total, disk, files, dirs)


class PropsDialog(QDialog):
    def __init__(self, parent, paths):
        super().__init__(parent)
        self.paths = [os.path.normpath(p) if len(p) > 3 else p for p in paths]
        self.worker = None
        one = len(self.paths) == 1
        p0 = self.paths[0]
        self.setWindowTitle("Свойства" + (f": {os.path.basename(p0) or p0}" if one else ""))
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(520, 440)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # --- шапка: значок и имя ---
        head = QHBoxLayout()
        icon = QLabel()
        try:
            pm = QFileIconProvider().icon(QFileInfo(p0)).pixmap(48, 48)
            icon.setPixmap(pm)
        except Exception:
            pass
        head.addWidget(icon)
        title = QLabel()
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title.setWordWrap(True)
        title.setText(f"<span style='font-size:16px'><b>{self._esc(os.path.basename(p0) or p0)}</b></span>" if one
                      else f"<span style='font-size:16px'><b>{len(self.paths)} "
                           f"{plural(len(self.paths), 'объект', 'объекта', 'объектов')}</b></span>")
        head.addWidget(title, 1)
        lay.addLayout(head)
        lay.addWidget(self._line())

        # --- таблица ---
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(7)
        self.grid.setColumnStretch(1, 1)
        lay.addLayout(self.grid)
        self._row = 0
        is_dir = os.path.isdir(p0)
        is_root = one and os.path.splitdrive(p0)[1] in ("\\", "")

        if one:
            self._add("Тип", self._type_of(p0, is_dir, is_root))
            self._add("Расположение", os.path.dirname(p0) if not is_root else "Этот компьютер", selectable=True)
        else:
            self._add("Тип", "Несколько объектов")
            folders = {os.path.dirname(p) for p in self.paths}
            self._add("Расположение", folders.pop() if len(folders) == 1 else "Разные папки", selectable=True)

        self.size_lbl = self._add("Размер", "считаю…" if (is_dir or not one) else "")
        self.disk_lbl = self._add("На диске", "считаю…" if (is_dir or not one) else "")
        self.cont_lbl = self._add("Содержит", "считаю…") if (is_dir or not one) else None

        if is_root:
            try:
                u = shutil.disk_usage(p0)
                self._add("Занято", f"{fmt_bytes(u.used)}")
                self._add("Свободно", f"{fmt_bytes(u.free)}")
                self._add("Ёмкость", f"{fmt_bytes(u.total)}")
            except OSError:
                pass

        if one and not is_root:
            try:
                st = os.stat(p0)
                if not is_dir:
                    self.size_lbl.setText(fmt_bytes(st.st_size))
                    d = size_on_disk(p0)
                    self.disk_lbl.setText(fmt_bytes(d) if d is not None else "—")
                self._add("Создан", fmt_date(st.st_ctime))
                self._add("Изменён", fmt_date(st.st_mtime))
                self._add("Открыт", fmt_date(st.st_atime))
            except OSError as e:
                self._add("Ошибка", e.strerror or "нет доступа")
        lay.addWidget(self._line())

        # --- атрибуты ---
        self.ck_ro = QCheckBox("Только чтение")
        self.ck_hid = QCheckBox("Скрытый")
        a = get_attrs(p0) if one else 0
        self.ck_ro.setChecked(bool(a & FILE_ATTRIBUTE_READONLY))
        self.ck_hid.setChecked(bool(a & FILE_ATTRIBUTE_HIDDEN))
        self._attrs0 = (self.ck_ro.isChecked(), self.ck_hid.isChecked())
        arow = QHBoxLayout()
        arow.addWidget(QLabel("Атрибуты:"))
        arow.addWidget(self.ck_ro)
        arow.addWidget(self.ck_hid)
        arow.addStretch(1)
        lay.addLayout(arow)
        if not one or is_root:
            self.ck_ro.setEnabled(False)
            self.ck_hid.setEnabled(False)
        self.msg = QLabel("")
        lay.addWidget(self.msg)
        lay.addStretch(1)

        # --- кнопки ---
        row = QHBoxLayout()
        if one and not is_dir:
            b = QPushButton("Контрольные суммы…")
            b.clicked.connect(self._hashes)
            row.addWidget(b)
        b2 = QPushButton("Системные свойства…")
        b2.setToolTip("Окно Windows: безопасность, предыдущие версии и прочее")
        b2.clicked.connect(lambda: sh.properties(p0))
        row.addWidget(b2)
        row.addStretch(1)
        self.btn_apply = QPushButton("Применить")
        self.btn_apply.clicked.connect(self.apply)
        row.addWidget(self.btn_apply)
        c = QPushButton("Закрыть")
        c.setDefault(True)
        c.clicked.connect(self.close)
        row.addWidget(c)
        lay.addLayout(row)

        if is_dir or not one:
            self.worker = SizeWorker(self.paths)
            self.worker.done.connect(self._sized)
            self.worker.start()

    # ---------- мелочи ----------
    @staticmethod
    def _esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _line():
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setFrameShadow(QFrame.Sunken)
        return f

    def _add(self, name, value, selectable=False):
        k = QLabel(name + ":")
        k.setAlignment(Qt.AlignRight | Qt.AlignTop)
        v = QLabel(value)
        v.setWordWrap(True)
        v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.grid.addWidget(k, self._row, 0)
        self.grid.addWidget(v, self._row, 1)
        self._row += 1
        return v

    @staticmethod
    def _type_of(path, is_dir, is_root):
        if is_root:
            return "Локальный диск"
        if is_dir:
            return "Папка с файлами"
        ext = os.path.splitext(path)[1].lower()
        try:
            t = QFileIconProvider().type(QFileInfo(path))
            if t:
                return f"{t} ({ext})" if ext else t
        except Exception:
            pass
        return f"Файл {ext.lstrip('.').upper()}" if ext else "Файл"

    # ---------- действия ----------
    def _sized(self, total, disk, files, dirs):
        self.size_lbl.setText(fmt_bytes(total))
        self.disk_lbl.setText(fmt_bytes(disk))
        if self.cont_lbl is not None:
            self.cont_lbl.setText(f"{files} {plural(files, 'файл', 'файла', 'файлов')}, "
                                  f"{dirs} {plural(dirs, 'папка', 'папки', 'папок')}")

    def _hashes(self):
        from hashdlg import HashDialog
        HashDialog(self, self.paths[0]).exec()

    def apply(self):
        if len(self.paths) != 1:
            return
        p = self.paths[0]
        ro, hid = self.ck_ro.isChecked(), self.ck_hid.isChecked()
        bad = []
        if ro != self._attrs0[0] and not set_attr(p, FILE_ATTRIBUTE_READONLY, ro):
            bad.append("«Только чтение»")
        if hid != self._attrs0[1] and not set_attr(p, FILE_ATTRIBUTE_HIDDEN, hid):
            bad.append("«Скрытый»")
        a = get_attrs(p)
        self._attrs0 = (bool(a & FILE_ATTRIBUTE_READONLY), bool(a & FILE_ATTRIBUTE_HIDDEN))
        self.msg.setText("Не удалось изменить: " + ", ".join(bad) if bad else "Сохранено")

    def closeEvent(self, e):
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(e)
