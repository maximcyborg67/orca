"""Боковая панель: места, диски, закладки."""
import os

from PySide6.QtCore import Qt, Signal, QStandardPaths, QStorageInfo, QFileInfo, QRect, QSize, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette, QFont
from PySide6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QStyledItemDelegate, QFileIconProvider, QMenu)

import shellops as sh
from util import fmt_size, norm_path

PATH = Qt.UserRole
USED = Qt.UserRole + 1
KIND = Qt.UserRole + 2


class _Delegate(QStyledItemDelegate):
    def sizeHint(self, opt, idx):
        s = super().sizeHint(opt, idx)
        kind = idx.data(KIND)
        if kind == "header":
            return QSize(s.width(), 30)
        return QSize(s.width(), 44 if kind == "drive" else 32)

    def paint(self, p, opt, idx):
        if idx.data(KIND) == "drive":
            # название сверху, полоска занятости снизу
            from PySide6.QtWidgets import QStyleOptionViewItem
            o = QStyleOptionViewItem(opt)
            self.initStyleOption(o, idx)
            o.rect = QRect(opt.rect.left(), opt.rect.top(), opt.rect.width(), 30)
            super().paint(p, o, idx)
            frac = idx.data(USED)
            if frac is not None:
                pal = opt.palette
                left = opt.rect.left() + 34
                w = opt.rect.width() - 34 - 14
                y = opt.rect.bottom() - 9
                p.save()
                p.setRenderHint(QPainter.Antialiasing)
                p.setPen(Qt.NoPen)
                bg = QColor(pal.color(QPalette.Mid))
                p.setBrush(bg)
                p.drawRoundedRect(left, y, w, 5, 2.5, 2.5)
                col = QColor("#e5534b") if frac > 0.9 else QColor(pal.color(QPalette.Link))
                p.setBrush(col)
                p.drawRoundedRect(left, y, max(4, int(w * frac)), 5, 2.5, 2.5)
                p.restore()
            return
        super().paint(p, opt, idx)


class Sidebar(QTreeWidget):
    open_path = Signal(str)
    open_new_tab = Signal(str)
    files_dropped = Signal(list, str, bool, bool)   # файлы, куда, Ctrl, Shift
    bookmarks_changed = Signal(list)

    def __init__(self, bookmarks, recent=None):
        super().__init__()
        self.recent = recent if recent is not None else []          # общий список из настроек (его правит окно)
        self._recent_timer = QTimer(self)
        self._recent_timer.setSingleShot(True)
        self._recent_timer.setInterval(400)
        self._recent_timer.timeout.connect(self.build)
        self.setObjectName("sidebar")
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setItemDelegate(_Delegate(self))
        self.setIconSize(QSize(20, 20))
        self.setFocusPolicy(Qt.NoFocus)
        self.setAcceptDrops(True)
        self.setVerticalScrollMode(QTreeWidget.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(self._clicked)
        self.bookmarks = list(bookmarks)
        self._icons = QFileIconProvider()
        self._current = ""
        self._drive_sig = None
        self.build()
        t = QTimer(self)
        t.timeout.connect(self._poll_drives)
        t.start(4000)

    # ---------- построение ----------
    def _header(self, text):
        it = QTreeWidgetItem([text.upper()])
        it.setData(0, KIND, "header")
        it.setFlags(Qt.ItemIsEnabled)
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        it.setFont(0, f)
        it.setForeground(0, self.palette().color(QPalette.PlaceholderText))
        self.addTopLevelItem(it)
        return it

    def _item(self, label, path, kind, tip=None, frac=None):
        it = QTreeWidgetItem([label])
        it.setData(0, PATH, path)
        it.setData(0, KIND, kind)
        if frac is not None:
            it.setData(0, USED, frac)
        it.setIcon(0, self._icons.icon(QFileInfo(path)) if path else self._icons.icon(QFileIconProvider.Computer))
        if tip:
            it.setToolTip(0, tip)
        self.addTopLevelItem(it)
        return it

    def build(self):
        self.clear()
        sp = QStandardPaths
        self._header("Места")
        self._item("Этот компьютер", "", "place")
        places = [
            ("Домашняя папка", os.path.expanduser("~")),
            ("Рабочий стол", sp.writableLocation(sp.DesktopLocation)),
            ("Загрузки", sp.writableLocation(sp.DownloadLocation)),
            ("Документы", sp.writableLocation(sp.DocumentsLocation)),
            ("Изображения", sp.writableLocation(sp.PicturesLocation)),
            ("Музыка", sp.writableLocation(sp.MusicLocation)),
            ("Видео", sp.writableLocation(sp.MoviesLocation)),
        ]
        for label, p in places:
            if p and os.path.isdir(p):
                self._item(label, norm_path(p), "place")
        if self.bookmarks:
            self._header("Закладки")
            for p in self.bookmarks:
                self._item(os.path.basename(p.rstrip("\\")) or p, p, "bookmark", p)
        shown = [p for p in self.recent if os.path.isdir(p)][:8]
        if shown:
            self._header("Недавние")
            for p in shown:
                self._item(os.path.basename(p.rstrip("\\")) or p, p, "recent", p)
        self._header("Диски")
        self._drive_sig = self._drives_signature()
        for v in QStorageInfo.mountedVolumes():
            if not v.isValid() or not v.isReady():
                continue
            root = v.rootPath().replace("/", "\\")
            drive = root.rstrip("\\")
            label = f"{v.name() or 'Локальный диск'} ({drive})"
            total, free = v.bytesTotal(), v.bytesAvailable()
            frac = (total - free) / total if total else None
            tip = f"{fmt_size(free)} свободно из {fmt_size(total)}" if total else root
            self._item(label, root, "drive", tip, frac)
        self.expandAll()
        self._mark()

    def _props(self, path):
        from propsdlg import PropsDialog
        PropsDialog(self.window(), [path]).show()

    def _forget_recent(self, path):
        if path is None:
            self.recent.clear()
        else:
            self.recent[:] = [r for r in self.recent if r != path]
        self.build()

    def recent_changed(self):
        """Список недавних изменился — перерисуем панель чуть позже (не на каждый переход)."""
        self._recent_timer.start()

    def _drives_signature(self):
        # только список букв дисков — это не обращается к самим дискам (спящий диск не будим и не ждём)
        import ctypes
        return ctypes.windll.kernel32.GetLogicalDrives()

    def _poll_drives(self):
        self._ticks = getattr(self, "_ticks", 0) + 1
        sig = self._drives_signature()
        if sig != self._drive_sig or self._ticks % 75 == 0:      # шкалы места обновляем раз в 5 минут
            self.build()

    def set_current(self, path):
        self._current = path
        self._mark()

    def _mark(self):
        self.blockSignals(True)
        self.clearSelection()
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it.data(0, KIND) != "header" and it.data(0, PATH) is not None \
                    and norm_path(it.data(0, PATH)).lower() == self._current.lower():
                it.setSelected(True)
                break
        self.blockSignals(False)

    # ---------- закладки ----------
    def add_bookmark(self, path):
        path = norm_path(path)
        if path and path not in self.bookmarks:
            self.bookmarks.append(path)
            self.bookmarks_changed.emit(self.bookmarks)
            self.build()

    def remove_bookmark(self, path):
        if path in self.bookmarks:
            self.bookmarks.remove(path)
            self.bookmarks_changed.emit(self.bookmarks)
            self.build()

    # ---------- события ----------
    def _clicked(self, it, col):
        if it.data(0, KIND) == "header":
            return
        p = it.data(0, PATH)
        if p is not None:
            self.open_path.emit(p)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            it = self.itemAt(e.position().toPoint())
            if it is not None and it.data(0, KIND) != "header":
                self.open_new_tab.emit(it.data(0, PATH) or "")
            return
        super().mousePressEvent(e)

    def _menu(self, pos):
        it = self.itemAt(pos)
        if it is None or it.data(0, KIND) == "header":
            return
        path, kind = it.data(0, PATH), it.data(0, KIND)
        m = QMenu(self)
        m.addAction("Открыть").triggered.connect(lambda: self.open_path.emit(path))
        m.addAction("Открыть в новой вкладке").triggered.connect(lambda: self.open_new_tab.emit(path))
        if path and kind != "bookmark":
            m.addAction("Добавить в закладки").triggered.connect(lambda: self.add_bookmark(path))
        if kind == "bookmark":
            m.addAction("Убрать из закладок").triggered.connect(lambda: self.remove_bookmark(path))
        if kind == "recent":
            m.addAction("Убрать из недавних").triggered.connect(lambda: self._forget_recent(path))
            m.addAction("Очистить весь список").triggered.connect(lambda: self._forget_recent(None))
        if path:
            m.addSeparator()
            m.addAction("Свойства").triggered.connect(lambda: self._props(path))
        m.exec(self.viewport().mapToGlobal(pos))

    # ---------- перетаскивание на место/диск ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        it = self.itemAt(e.position().toPoint())
        if e.mimeData().hasUrls() and it is not None and it.data(0, KIND) not in ("header", None) \
                and it.data(0, PATH):
            e.acceptProposedAction()
            self.setCurrentItem(it)
        else:
            e.ignore()

    def dropEvent(self, e):
        it = self.itemAt(e.position().toPoint())
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if it is not None and it.data(0, PATH) and urls:
            mods = e.keyboardModifiers()
            self.files_dropped.emit(urls, it.data(0, PATH), bool(mods & Qt.ControlModifier),
                                    bool(mods & Qt.ShiftModifier))
            e.setDropAction(Qt.CopyAction)
            e.accept()
        self._mark()
