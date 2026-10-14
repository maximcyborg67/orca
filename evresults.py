"""Результаты поиска Everything: «виртуальный» список — в памяти только видимые страницы, поэтому не тормозит
даже на миллионе найденных файлов (раньше каждый результат был отдельным элементом списка)."""
import os
from datetime import datetime

from PySide6.QtCore import (Qt, QAbstractTableModel, QModelIndex, QObject, QRunnable, QThreadPool, QTimer, Signal,
                            QMimeData, QUrl, QFileInfo)
from PySide6.QtWidgets import QAbstractItemView, QFileIconProvider, QHeaderView, QTreeView

import everything
from util import fmt_size

PAGE = 400
EXCLUDE = ' !"\\$recycle.bin\\" !"\\system volume information\\"'


class _Sig(QObject):
    got = Signal(int, int, int, list)      # поколение, страница, всего найдено, строки
    failed = Signal(int, str)


class _Job(QRunnable):
    def __init__(self, sig, gen, page, text, sort, fn):
        super().__init__()
        self.sig, self.gen, self.page, self.text, self.sort, self.fn = sig, gen, page, text, sort, fn

    def run(self):
        try:
            r = self.fn(self.text, self.page * PAGE, PAGE, self.sort)
        except Exception as e:                         # noqa: BLE001
            self.sig.failed.emit(self.gen, str(e))
            return
        if r is None:
            self.sig.failed.emit(self.gen, "Everything не отвечает")
        else:
            self.sig.got.emit(self.gen, self.page, r[0], r[1])


def default_fetch(text, offset, count, sort):
    """Запрос к Everything (при необходимости сам её запускает). None — не отвечает."""
    hwnd = everything.ensure_running()
    if not hwnd:
        return None
    return everything.query(text, offset, count, sort, hwnd=hwnd)


SORT_BY_COL = {0: ("name", "name_desc"), 1: ("path", "path_desc"), 2: ("size", "size_desc"), 3: ("date", "date_desc")}


class EverythingModel(QAbstractTableModel):
    status = Signal()
    error = Signal(str)
    HEADERS = ("Имя", "Папка", "Размер", "Изменён")

    def __init__(self, fetch=default_fetch, parent=None):
        super().__init__(parent)
        self.fetch = fetch
        self.total = 0
        self.pages = {}
        self.pending = set()
        self.text = ""
        self.sort_key = "name"
        self.gen = 0
        self.loading = False
        self.sig = _Sig()
        self.sig.got.connect(self._got)
        self.sig.failed.connect(self._failed)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._icons = QFileIconProvider()
        self._folder = self._icons.icon(QFileIconProvider.Folder)
        self._file = self._icons.icon(QFileIconProvider.File)
        self._ext = {}

    # ---------- запросы ----------
    def start(self, text):
        self.beginResetModel()
        self.gen += 1
        self.text = text
        self.total = 0
        self.pages.clear()
        self.pending.clear()
        self.loading = True
        self.endResetModel()
        self._request(0)
        self.status.emit()

    def clear(self):
        self.beginResetModel()
        self.gen += 1
        self.total = 0
        self.pages.clear()
        self.pending.clear()
        self.loading = False
        self.endResetModel()

    def sort(self, column, order=Qt.AscendingOrder):
        asc, desc = SORT_BY_COL.get(column, ("name", "name_desc"))
        key = desc if order == Qt.DescendingOrder else asc
        if key != self.sort_key:
            self.sort_key = key
            if self.text:
                self.start(self.text)

    def _request(self, page):
        if page in self.pages or page in self.pending or page < 0:
            return
        if self.total and page * PAGE >= self.total:
            return
        self.pending.add(page)
        self.pool.start(_Job(self.sig, self.gen, page, self.text, self.sort_key, self.fetch))

    def _got(self, gen, page, total, rows):
        if gen != self.gen:
            return
        self.pending.discard(page)
        first = self.total == 0
        self.pages[page] = rows
        if first and total != self.total:        # число находок берём с первой страницы; дальше список не «прыгает»
            self.beginResetModel()
            self.total = total
            self.endResetModel()
        if page == 0:
            self.loading = False
        n = len(rows)
        if n and page * PAGE < self.total:
            self.dataChanged.emit(self.index(page * PAGE, 0), self.index(min(self.total - 1, page * PAGE + n - 1), 3))
        self.status.emit()

    def _failed(self, gen, msg):
        if gen != self.gen:
            return
        self.loading = False
        self.error.emit(msg)
        self.status.emit()

    # ---------- данные ----------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.total

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < 4:
            return self.HEADERS[section]
        return None

    def _row(self, r, want=True):
        page = r // PAGE
        rows = self.pages.get(page)
        if rows is None:
            if want:
                self._request(page)
            return None
        i = r - page * PAGE
        return rows[i] if i < len(rows) else None

    def row_data(self, r):
        return self._row(r, want=False)

    def _icon(self, row):
        path, is_dir = row[0], row[1]
        if is_dir:
            return self._folder
        ext = os.path.splitext(path)[1].lower()
        ic = self._ext.get(ext)
        if ic is None:
            ic = self._icons.icon(QFileInfo("C:/__orca__/x" + ext)) if ext else self._file
            self._ext[ext] = ic
        return ic

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._row(index.row())
        c = index.column()
        if role == Qt.DisplayRole:
            if row is None:
                return "…" if c == 0 else ""
            path, is_dir, size, mt = row
            if c == 0:
                return os.path.basename(path) or path
            if c == 1:
                return os.path.dirname(path)
            if c == 2:
                return "" if is_dir else fmt_size(size)
            return datetime.fromtimestamp(mt).strftime("%d.%m.%Y  %H:%M") if mt else ""
        if role == Qt.DecorationRole and c == 0 and row is not None:
            return self._icon(row)
        if role == Qt.TextAlignmentRole and c == 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole and row is not None:
            return row[0]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled

    def paths_for_rows(self, rows):
        """Пути строк; страницы, которых ещё нет, догружаются сразу (нужно для копирования, удаления и т.п.)."""
        out = []
        need = sorted({r // PAGE for r in rows if r // PAGE not in self.pages})
        for page in need:
            res = self.fetch(self.text, page * PAGE, PAGE, self.sort_key)
            if res:
                self.pages[page] = res[1]
        for r in rows:
            row = self._row(r, want=False)
            if row is not None:
                out.append(os.path.normpath(row[0]))
        return out

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        md = QMimeData()
        rows = sorted({i.row() for i in indexes})
        md.setUrls([QUrl.fromLocalFile(p) for p in self.paths_for_rows(rows[:2000])])
        return md

    def supportedDragActions(self):
        return Qt.CopyAction


class EverythingResults(QTreeView):
    """Тот же набор методов, что у SearchResults, поэтому окно папки работает с ним одинаково."""

    def __init__(self):
        super().__init__()
        self.mdl = EverythingModel()
        self.setModel(self.mdl)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.AscendingOrder)
        hd = self.header()
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(0, QHeaderView.Interactive)
        hd.setSectionResizeMode(1, QHeaderView.Stretch)
        self.setColumnWidth(0, 340)
        self.setColumnWidth(2, 100)
        self.setColumnWidth(3, 150)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.folder = None

    def attach(self, folder):
        self.folder = folder

    def clear(self):
        self.mdl.clear()

    def topLevelItemCount(self):
        return self.mdl.total

    def selected_paths(self):
        rows = set()
        for rng in self.selectionModel().selection():
            rows.update(range(rng.top(), min(rng.bottom(), self.mdl.total - 1) + 1))
        return self.mdl.paths_for_rows(sorted(rows)[:50000])

    def prune(self):
        pass

    def selectAll(self):
        """Ctrl+A: первые 20 000 найденных (на миллион строк Qt выделял бы минутами)."""
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        n = min(self.mdl.total, 20000)
        if n:
            sel = QItemSelection(self.mdl.index(0, 0), self.mdl.index(n - 1, 0))
            self.selectionModel().select(sel, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    def keyPressEvent(self, e):
        host = self.folder.host
        if e.key() == Qt.Key_Space and not e.modifiers():
            host.toggle_quicklook()
            return
        if e.key() == Qt.Key_Escape and host.quicklook.isVisible():
            host.quicklook.hide_it()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            idx = self.currentIndex()
            row = self.mdl.row_data(idx.row()) if idx.isValid() else None
            if row:
                self.folder.open_path(os.path.normpath(row[0]))
            return
        super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        row = self.mdl.row_data(idx.row()) if idx.isValid() else None
        if row:
            self.folder.open_path(os.path.normpath(row[0]))
            return
        super().mouseDoubleClickEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.BackButton:
            self.folder.close_search()
            return
        if e.button() == Qt.MiddleButton:
            idx = self.indexAt(e.position().toPoint())
            row = self.mdl.row_data(idx.row()) if idx.isValid() else None
            if row and row[1]:
                self.folder.new_tab_requested.emit(os.path.normpath(row[0]))
            return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        idx = self.indexAt(e.pos())
        if idx.isValid() and not self.selectionModel().isSelected(idx):
            self.setCurrentIndex(idx)
            self.selectionModel().select(idx, self.selectionModel().SelectionFlag.ClearAndSelect |
                                         self.selectionModel().SelectionFlag.Rows)
        self.folder.show_context(e.globalPos(), idx.isValid())
