"""Поиск по имени в папке и всех вложенных: работает в фоне, результаты появляются сразу."""
import fnmatch
import os
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal, QMimeData, QUrl, QFileInfo
from PySide6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QAbstractItemView, QFileIconProvider, QHeaderView)

from util import fmt_size

MAX_RESULTS = 20000
HIDDEN = 0x2


def make_matcher(text):
    """Все слова должны встретиться в имени; * и ? работают как подстановки."""
    words = [w for w in text.lower().split() if w]
    if not words:
        return None
    plain = [w for w in words if "*" not in w and "?" not in w]
    wild = [w for w in words if "*" in w or "?" in w]

    def match(name):
        n = name.lower()
        return all(w in n for w in plain) and all(fnmatch.fnmatchcase(n, w) for w in wild)

    return match


_ALIVE = set()   # пока поток работает, на него должна быть ссылка, иначе Qt падает


def stop_all():
    for w in list(_ALIVE):
        w.cancel()
    for w in list(_ALIVE):
        w.wait(3000)


class SearchWorker(QThread):
    found = Signal(list)          # пачка (путь, папка?, размер, время)
    finished_search = Signal(bool)  # True — прервано

    def __init__(self, root, text, show_hidden):
        super().__init__()
        _ALIVE.add(self)
        self.finished.connect(lambda: (self.wait(), _ALIVE.discard(self)))
        self.root = root
        self.match = make_matcher(text)
        self.show_hidden = show_hidden
        self._cancel = False
        self.count = 0

    def cancel(self):
        self._cancel = True

    def run(self):
        batch = []
        stack = [self.root]
        try:
            while stack and not self._cancel:
                cur = stack.pop()
                try:
                    it = os.scandir(cur)
                except OSError:
                    continue
                with it:
                    for e in it:
                        if self._cancel:
                            break
                        try:
                            st = e.stat(follow_symlinks=False)
                            if not self.show_hidden and getattr(st, "st_file_attributes", 0) & HIDDEN:
                                continue
                            is_dir = e.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        if is_dir:
                            stack.append(e.path)
                        if self.match(e.name):
                            batch.append((e.path, is_dir, 0 if is_dir else st.st_size, st.st_mtime))
                            self.count += 1
                            if self.count >= MAX_RESULTS:
                                self._cancel = True
                                break
                            if len(batch) >= 60:
                                self.found.emit(batch)
                                batch = []
        finally:
            if batch:
                self.found.emit(batch)
            self.finished_search.emit(self._cancel)


class SearchResults(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setColumnCount(4)
        self.setHeaderLabels(["Имя", "Папка", "Размер", "Изменён"])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.AscendingOrder)
        self.setIconSize(self.iconSize().expandedTo(self.iconSize()))
        hd = self.header()
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(0, QHeaderView.Interactive)
        hd.setSectionResizeMode(1, QHeaderView.Stretch)
        self.setColumnWidth(0, 340)
        self.setColumnWidth(2, 100)
        self.setColumnWidth(3, 150)
        self._icons = QFileIconProvider()
        self._cache = {}
        self.folder = None

    def attach(self, folder):
        self.folder = folder

    def _icon(self, path, is_dir):
        key = "<dir>" if is_dir else os.path.splitext(path)[1].lower() or path
        ic = self._cache.get(key)
        if ic is None:
            ic = self._icons.icon(QFileInfo(path))
            if len(self._cache) < 500:
                self._cache[key] = ic
        return ic

    def add_batch(self, rows):
        self.setSortingEnabled(False)
        for path, is_dir, size, mtime in rows:
            it = _Item([os.path.basename(path), os.path.dirname(path),
                        "" if is_dir else fmt_size(size),
                        datetime.fromtimestamp(mtime).strftime("%d.%m.%Y  %H:%M")])
            it.setData(0, Qt.UserRole, path)
            it.setData(2, Qt.UserRole, -1 if is_dir else size)
            it.setData(3, Qt.UserRole, mtime)
            it.setData(0, Qt.UserRole + 1, is_dir)
            it.setIcon(0, self._icon(path, is_dir))
            self.addTopLevelItem(it)
        self.setSortingEnabled(True)

    def selected_paths(self):
        return [os.path.normpath(i.data(0, Qt.UserRole)) for i in self.selectedItems()]

    def prune(self):
        """Убрать из списка то, чего уже нет на диске (после удаления или переноса)."""
        for i in reversed(range(self.topLevelItemCount())):
            if not os.path.exists(self.topLevelItem(i).data(0, Qt.UserRole)):
                self.takeTopLevelItem(i)

    def keyPressEvent(self, e):
        host = self.folder.host
        if e.key() == Qt.Key_Space and not e.modifiers():
            host.toggle_quicklook()
            return
        if e.key() == Qt.Key_Escape and host.quicklook.isVisible():
            host.quicklook.hide_it()
            return
        super().keyPressEvent(e)

    # ---- мышь ----
    def mousePressEvent(self, e):
        if e.button() == Qt.BackButton:
            self.folder.close_search()
            return
        if e.button() == Qt.MiddleButton:
            it = self.itemAt(e.position().toPoint())
            if it is not None and it.data(0, Qt.UserRole + 1):
                self.folder.new_tab_requested.emit(it.data(0, Qt.UserRole))
            return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        it = self.itemAt(e.pos())
        if it is not None and not it.isSelected():
            self.clearSelection()
            it.setSelected(True)
            self.setCurrentItem(it)
        self.folder.show_context(e.globalPos(), it is not None)

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(i.data(0, Qt.UserRole)) for i in items])
        return md

    def mimeTypes(self):
        return ["text/uri-list"]


class _Item(QTreeWidgetItem):
    """Сортировка по размеру и дате — по числам, а не по тексту; папки идут первыми по имени."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col in (2, 3):
            return (self.data(col, Qt.UserRole) or 0) < (other.data(col, Qt.UserRole) or 0)
        a_dir, b_dir = self.data(0, Qt.UserRole + 1), other.data(0, Qt.UserRole + 1)
        if a_dir != b_dir and col == 0:
            asc = self.treeWidget().header().sortIndicatorOrder() == Qt.AscendingOrder
            return bool(a_dir) == asc
        return self.text(col).lower() < other.text(col).lower()
