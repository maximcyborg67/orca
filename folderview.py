"""Одна вкладка: путь, кнопки «назад/вперёд/вверх» и сам список файлов (значки / компактно / подробно)."""
import os

from PySide6.QtCore import Qt, Signal, QSize, QTimer, QModelIndex, QFileInfo, QItemSelectionModel
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QTreeView, QListView,
                               QAbstractItemView, QStyledItemDelegate, QStyleOptionViewItem, QLineEdit, QMenu, QHeaderView,
                               QApplication)

import shellops as sh
import vfs
from fsmodel import FsModel
from pathbar import PathBar
from searchpanel import SearchResults, SearchWorker
from fileindex import IndexSearchWorker
from ui import G, glyph_button
from util import fmt_size, plural, norm_path, unique_name

MODES = ("icons", "compact", "details")


class NameDelegate(QStyledItemDelegate):
    """При переименовании выделяет только имя без расширения (как в Проводнике).
    В режимах «значки» и «компактно» размер ячейки задан жёстко — иначе длинное имя первого файла
    сжимало все ячейки, и подписи пропадали."""
    fixed = None

    def sizeHint(self, option, index):
        if self.fixed is not None and index.column() == 0:
            return self.fixed
        return super().sizeHint(option, index)

    def createEditor(self, parent, option, index):
        ed = super().createEditor(parent, option, index)
        if isinstance(ed, QLineEdit):
            import theme
            c = theme.colors()
            # свой стиль без больших отступов поля поиска — иначе в низкой строке текст сжимается
            ed.setStyleSheet(
                f"QLineEdit {{ padding: 0px 4px; border: 1px solid {c['accent']}; border-radius: 4px;"
                f" background: {c['alt']}; color: {c['text']}; }}")
            ed.setFont(option.font)
            ed.setFrame(False)
            ed.setAlignment(Qt.AlignCenter if option.decorationPosition == QStyleOptionViewItem.Position.Top
                            else Qt.AlignLeft | Qt.AlignVCenter)
        return ed

    def updateEditorGeometry(self, editor, option, index):
        super().updateEditorGeometry(editor, option, index)
        if not isinstance(editor, QLineEdit):
            return
        r = option.rect
        fm = editor.fontMetrics()
        h = max(fm.height() + 8, 24)
        if option.decorationPosition == QStyleOptionViewItem.Position.Top:   # вид «значки»: поле под значком
            w = max(r.width() - 4, 90)
            editor.setGeometry(r.left() + (r.width() - w) // 2, r.bottom() - h - 2, w, h)
        else:
            g = editor.geometry()
            editor.setGeometry(g.left(), r.top() + (r.height() - h) // 2, max(g.width(), 120), h)

    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)
        if isinstance(editor, QLineEdit):
            text = editor.text()
            stem = text if index.model().isDir(index) else os.path.splitext(text)[0]
            QTimer.singleShot(0, lambda: editor.setSelection(0, len(stem)) if editor else None)


class ViewMixin:
    """Общее для всех видов: мышь, меню, перетаскивание."""

    def attach(self, folder):
        self.folder = folder
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)   # иначе правая кнопка не вызывает меню
        self.name_delegate = NameDelegate(self)
        self.setItemDelegateForColumn(0, self.name_delegate)
        self.setUniformItemSizes(True) if hasattr(self, "setUniformItemSizes") else None

    def mousePressEvent(self, e):
        if e.button() == Qt.BackButton:
            self.folder.back()
            return
        if e.button() == Qt.ForwardButton:
            self.folder.forward()
            return
        if e.button() == Qt.MiddleButton:
            idx = self.indexAt(e.position().toPoint())
            if idx.isValid() and self.model().isDir(idx.siblingAtColumn(0)):
                self.folder.new_tab_requested.emit(self.model().filePath(idx))
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() in (Qt.MiddleButton, Qt.BackButton, Qt.ForwardButton):
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        host = self.folder.host
        if e.key() == Qt.Key_Space and not e.modifiers() and self.state() != QAbstractItemView.EditingState:
            host.toggle_quicklook()
            return
        if e.key() == Qt.Key_Escape and host.quicklook.isVisible():
            host.quicklook.hide_it()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and host.quicklook.isVisible():
            host.quicklook.hide_it()
        super().keyPressEvent(e)

    def selectAll(self):
        """Ctrl+A одним диапазоном — в папке на десятки тысяч файлов стандартный способ тормозит."""
        m = self.model()
        n = m.rowCount()
        if n == 0:
            return
        from PySide6.QtCore import QItemSelection
        sel = QItemSelection(m.index(0, 0), m.index(n - 1, 0))      # только столбец имён; «Rows» растянет на строку
        flag = QItemSelectionModel.ClearAndSelect
        if isinstance(self, QTreeView):
            flag |= QItemSelectionModel.Rows
        self.selectionModel().select(sel, flag)

    def contextMenuEvent(self, e):
        idx = self.indexAt(e.pos())
        if idx.isValid():
            idx = idx.siblingAtColumn(0)
            if not self.selectionModel().isSelected(idx):
                self.setCurrentIndex(idx)
                self.selectionModel().select(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        else:
            self.clearSelection()
        self.folder.show_context(e.globalPos(), idx.isValid())

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.folder.zoom(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    # ----- перетаскивание -----
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        super().dragMoveEvent(e)
        if e.mimeData().hasUrls():
            e.setDropAction(Qt.CopyAction if e.keyboardModifiers() & Qt.ControlModifier else Qt.MoveAction)
            e.accept()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        try:
            self.setState(QAbstractItemView.NoState)
        except Exception:
            pass
        self.viewport().update()
        if not urls:
            return
        target = self.folder.path
        idx = self.indexAt(e.position().toPoint())
        if idx.isValid():
            idx = idx.siblingAtColumn(0)
            if self.model().isDir(idx):
                target = os.path.normpath(self.model().filePath(idx))
        if not target:
            return
        mods = e.keyboardModifiers()
        ops = self.folder.ops
        copy = ops.default_copy(urls, target, bool(mods & Qt.ControlModifier), bool(mods & Qt.ShiftModifier))
        ops.transfer(urls, target, copy)
        e.setDropAction(Qt.CopyAction)
        e.accept()


class TreeView(ViewMixin, QTreeView):
    pass


class ListView(ViewMixin, QListView):
    pass


class FolderView(QWidget):
    path_changed = Signal(object)
    selection_changed = Signal(object)
    status_changed = Signal(object)
    new_tab_requested = Signal(str)

    def __init__(self, host, path, mode="details"):
        super().__init__()
        self.host = host
        self.ops = host.ops
        self._path = None
        self._hist = []
        self._hi = -1
        self._select_after = None
        self._name_filter = ""
        self.mode = mode if mode in MODES else "details"
        self.icon_size = int(host.settings.get("icon_size", 96))

        self.model = FsModel(self)
        self.model.tags = host.tags
        self.model.error.connect(lambda m: self.host.flash(m))
        self.model.renamed.connect(self._on_renamed)
        self.model.directoryLoaded.connect(self._on_loaded)
        self.model.rowsInserted.connect(self._schedule_status)
        self.model.rowsRemoved.connect(self._schedule_status)
        self.model.layoutChanged.connect(self._schedule_status)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(250)
        self._status_timer.timeout.connect(self._emit_status)
        self._apply_filter()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 0)
        lay.setSpacing(6)
        nav = QHBoxLayout()
        nav.setSpacing(2)
        self.btn_back = glyph_button(G["back"], "Назад (Alt+←)")
        self.btn_fwd = glyph_button(G["forward"], "Вперёд (Alt+→)")
        self.btn_up = glyph_button(G["up"], "Вверх (Alt+↑)")
        self.btn_refresh = glyph_button(G["refresh"], "Обновить (F5)")
        for b in (self.btn_back, self.btn_fwd, self.btn_up):
            nav.addWidget(b)
        self.pathbar = PathBar()
        nav.addWidget(self.pathbar, 1)
        nav.addWidget(self.btn_refresh)
        lay.addLayout(nav)
        self.btn_back.clicked.connect(self.back)
        self.btn_fwd.clicked.connect(self.forward)
        self.btn_up.clicked.connect(self.up)
        self.btn_refresh.clicked.connect(self.refresh)
        self.pathbar.navigate.connect(self.navigate)
        self.pathbar.files_dropped.connect(
            lambda urls, target, c, s: self.ops.transfer(urls, target, self.ops.default_copy(urls, target, c, s)))

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        self.tree = TreeView()
        self.tree.setModel(self.model)
        self.tree.attach(self)
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        hd = self.tree.header()
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, w in ((1, 100), (2, 200), (3, 160)):
            hd.setSectionResizeMode(col, QHeaderView.Interactive)
            self.tree.setColumnWidth(col, w)
        self.tree.setColumnWidth(0, 420)

        self.list = ListView()
        self.list.setModel(self.model)
        self.list.setSelectionModel(self.tree.selectionModel())
        self.list.attach(self)
        self.list.setMovement(QListView.Static)
        self.list.setDragEnabled(True)                      # setMovement(Static) выключает перенос файлов, возвращаем
        self.list.viewport().setAcceptDrops(True)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setWrapping(True)
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.ElideMiddle)
        self.list.setSpacing(2)

        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.list)

        # поиск по вложенным папкам
        self.results = SearchResults()
        self.results.attach(self)
        self.stack.addWidget(self.results)
        self._worker = None
        self._searching = False
        self.search_active = False
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по имени в этой папке и во вложенных… (Enter — искать, Esc — закрыть)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.start_search)
        from PySide6.QtWidgets import QComboBox
        self.scope = QComboBox()
        self.scope.addItems(["В этой папке", "По всему ПК"])
        self.scope.setToolTip("Где искать: в открытой папке и вложенных или по всему компьютеру (по индексу, почти мгновенно)")
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.search_row = QWidget()
        _sr = QHBoxLayout(self.search_row)
        _sr.setContentsMargins(0, 0, 0, 0)
        _sr.addWidget(self.search_edit, 1)
        _sr.addWidget(self.scope)
        self.search_row.hide()
        self.search_edit.installEventFilter(self)
        self.results.itemActivated.connect(lambda it, c: self.open_path(it.data(0, Qt.UserRole)))
        self.results.itemSelectionChanged.connect(lambda: self.selection_changed.emit(self))
        # результаты Everything (виртуальный список для сотен тысяч строк)
        from evresults import EverythingResults
        self.eresults = EverythingResults()
        self.eresults.attach(self)
        self.stack.addWidget(self.eresults)
        self._ev_mode = False
        self.eresults.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed.emit(self))
        self.eresults.mdl.status.connect(self._emit_status)
        self.eresults.mdl.error.connect(self._everything_failed)
        self._live = QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(280)
        self._live.timeout.connect(self._live_search)
        self.search_edit.textChanged.connect(self._search_text_changed)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Фильтр по имени… (Esc — закрыть)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.hide()
        self.filter_edit.textChanged.connect(self._filter_changed)
        self.filter_edit.installEventFilter(self)
        lay.addWidget(self.filter_edit)
        lay.addWidget(self.search_row)

        for v in (self.tree, self.list):
            v.activated.connect(self._activated)
        sm = self.tree.selectionModel()
        sm.selectionChanged.connect(lambda *_: self.selection_changed.emit(self))
        sm.currentChanged.connect(lambda *_: self.selection_changed.emit(self))

        self.set_mode(self.mode, init=True)
        self.navigate(path, push=True)

    # ---------- свойства ----------
    @property
    def path(self):
        return self._path or ""

    def title(self):
        p = self.path
        if not p:
            return "Этот компьютер"
        name = os.path.basename(p.rstrip("\\"))
        return name or p.rstrip("\\")

    def view(self):
        if self.search_active:
            return self._res()
        return self.tree if self.mode == "details" else self.list

    def focus_view(self):
        self.view().setFocus()

    # ---------- навигация ----------
    def navigate(self, path, push=True, select=None):
        path = norm_path(path)
        if path and not vfs.isdir(path):
            self.host.flash(f"Папка недоступна: {path}")
            return False
        if self.search_active:
            self.close_search(focus=False)
        if self._path is not None and path == self._path:
            return True
        if push:
            del self._hist[self._hi + 1:]
            self._hist.append(path)
            self._hi = len(self._hist) - 1
        self._path = path
        self._select_after = select
        self.filter_edit.blockSignals(True)
        self.filter_edit.clear()
        self.filter_edit.blockSignals(False)
        self._name_filter = ""
        self.filter_edit.hide()
        self._apply_filter()
        self.model.setRootPath(path)
        self.tree.setRootIndex(QModelIndex())
        self.list.setRootIndex(QModelIndex())
        self.tree.clearSelection()
        self.tree.scrollToTop()
        self.list.scrollToTop()
        self.pathbar.set_path(path)
        self._update_nav()
        self.host.note_recent(path)
        self.path_changed.emit(self)
        self._schedule_status()
        if select:
            QTimer.singleShot(60, self._try_select)
        return True

    def _update_nav(self):
        self.btn_back.setEnabled(self._hi > 0)
        self.btn_fwd.setEnabled(self._hi < len(self._hist) - 1)
        self.btn_up.setEnabled(bool(self._path))

    def back(self):
        if self._hi > 0:
            self._hi -= 1
            prev = self._path
            self._go_hist(select=prev)

    def forward(self):
        if self._hi < len(self._hist) - 1:
            self._hi += 1
            self._go_hist()

    def _go_hist(self, select=None):
        p = self._hist[self._hi]
        cur, self._path = self._path, None
        if not self.navigate(p, push=False, select=select):
            self._path = cur

    def up(self):
        p = self.path
        if not p:
            return
        parent = os.path.dirname(p.rstrip("\\"))
        if len(p.rstrip("\\")) <= 2 or not parent or parent == p.rstrip("\\"):
            parent = ""
        self.navigate(parent, select=p)

    def refresh(self):
        self.model.reload()
        self.host.flash("Обновлено", 1500)

    def _try_select(self, tries=25):
        target = self._select_after
        if not target:
            return
        root = self.tree.rootIndex()
        idx = self.model.index(target)
        if idx.isValid() and idx.parent() == root and self.model.rowCount(root) > 0:
            self.view().setCurrentIndex(idx)
            self.view().scrollTo(idx, QAbstractItemView.PositionAtCenter)
            self._select_after = None
        elif tries > 0:
            QTimer.singleShot(80, lambda: self._try_select(tries - 1))

    def _on_loaded(self, p):
        self._schedule_status()

    def _activated(self, idx):
        idx = idx.siblingAtColumn(0)
        self.open_index(idx)

    def open_index(self, idx):
        path = os.path.normpath(self.model.filePath(idx))
        self.open_path(path)

    def open_path(self, path):
        if vfs.is_virtual(path):
            if vfs.isdir(path):
                self.navigate(path)
            else:
                self._open_virtual_file(path)
            return
        if os.path.isdir(path):
            self.navigate(path)
            return
        if path.lower().endswith(vfs.OPEN_ON_ENTER) and os.path.isfile(path):
            import zipfile
            if zipfile.is_zipfile(path):
                self.navigate(path)           # .zip открываем как папку
                return
        if path.lower().endswith(".lnk"):
            target = QFileInfo(path).symLinkTarget()
            if target and os.path.isdir(target):
                self.navigate(target)
                return
        try:
            sh.open_file(path)
        except OSError as e:
            self.host.flash(f"Не удалось открыть: {e}")

    def _open_virtual_file(self, path):
        """Файл из архива: достаём во временную папку и открываем программой по умолчанию."""
        self.host.flash("Достаю файл…", 8000)

        def work():
            return vfs.materialize([path])

        def done(v):
            if isinstance(v, tuple) and v and v[0] == "error":
                self.host.flash("Не удалось открыть: " + v[1])
                return
            real, err = v
            if not real:
                self.host.flash("Не удалось получить файл: " + (err or "ошибка"))
                return
            try:
                sh.open_file(real[0])
                self.host.flash("Открыто (копия во временной папке)", 3000)
            except OSError as e:
                self.host.flash(f"Не удалось открыть: {e}")
        self.ops.bg(work, done)

    # ---------- виды ----------
    def set_mode(self, mode, init=False):
        self.mode = mode
        self.model.show_thumbs = (mode == "icons")
        if mode == "details":
            self.stack.setCurrentWidget(self.tree)
        else:
            self._configure_list()
            self.stack.setCurrentWidget(self.list)
        if not init:
            self.focus_view()
            self.view().viewport().update()
            self.host.mode_changed(self)

    def _configure_list(self):
        l = self.list
        if self.mode == "icons":
            s = self.icon_size
            l.setViewMode(QListView.IconMode)
            l.setFlow(QListView.LeftToRight)
            l.setIconSize(QSize(s, s))
            l.setGridSize(QSize(s + 44, s + 42))
            l.name_delegate.fixed = QSize(s + 36, s + 40)
            l.setUniformItemSizes(True)
            l.setWordWrap(True)
        else:
            l.setViewMode(QListView.ListMode)
            l.setFlow(QListView.TopToBottom)
            l.setIconSize(QSize(20, 20))
            l.setGridSize(QSize(270, 28))
            l.name_delegate.fixed = QSize(262, 26)
            l.setUniformItemSizes(True)
            l.setWordWrap(False)
            l.setTextElideMode(Qt.ElideRight)
        l.setMovement(QListView.Static)
        l.setDragEnabled(True)                              # setMovement(Static) выключает перенос файлов, возвращаем
        l.viewport().setAcceptDrops(True)
        l.setWrapping(True)
        l.setResizeMode(QListView.Adjust)

    def zoom(self, step):
        if self.mode != "icons":
            return
        self.set_icon_size(self.icon_size + step * 16)

    def set_icon_size(self, px):
        px = max(32, min(256, int(px)))
        self.icon_size = px
        if self.mode == "icons":
            self._configure_list()
        self.host.icon_size_changed(self)

    # ---------- фильтр / скрытые ----------
    def _apply_filter(self):
        self.model.set_filter(self.host.show_hidden, self._name_filter)

    def apply_hidden(self):
        self._apply_filter()

    def show_filter(self):
        self.filter_edit.show()
        self.filter_edit.setFocus()
        self.filter_edit.selectAll()

    def _filter_changed(self, text):
        self._name_filter = text.strip()
        self._apply_filter()
        self._schedule_status()

    # ---------- поиск ----------
    def _res(self):
        """Какой список результатов сейчас показан: Everything или обычный."""
        return self.eresults if self._ev_mode else self.results

    def _use_everything(self):
        import everything
        return bool(self.host.settings.get("use_everything", True)) and everything.installed()

    def _scope_changed(self, i):
        if i == 1 and self._use_everything():
            hint = "Поиск по всему компьютеру через Everything — мгновенно, можно писать *.jpg, ext:pdf, size:>1gb… (Esc — закрыть)"
        elif i == 1:
            hint = "Поиск по имени по всему компьютеру (по индексу)… Enter — искать, Esc — закрыть"
        else:
            hint = "Поиск по имени в этой папке и во вложенных… (Enter — искать, Esc — закрыть)"
        self.search_edit.setPlaceholderText(hint)
        if self.search_edit.text().strip() and self.search_row.isVisible():
            self.start_search()

    def _search_text_changed(self, _t):
        """Для Everything ищем по мере набора (она отвечает за миллисекунды)."""
        if self.search_row.isVisible() and self.scope.currentIndex() == 1 and self._use_everything():
            if len(self.search_edit.text().strip()) >= 2:
                self._live.start()
            else:
                self._live.stop()

    def _live_search(self):
        if self.search_row.isVisible() and self.scope.currentIndex() == 1:
            self.start_search()

    def _everything_failed(self, msg):
        """Everything не ответила — тихо переключаемся на собственный индекс Orca."""
        self.host.flash(f"{msg}. Ищу по собственному индексу Orca.", 6000)
        text = self.search_edit.text().strip()
        if text and self.search_active and self._ev_mode:
            self._ev_mode = False
            self.start_search(force_index=True)

    def show_search(self, scope=None):
        if scope is None and not self.path:
            self.host.flash("Откройте диск или папку, в которой искать")
            return
        if scope is not None:
            self.scope.blockSignals(True)
            self.scope.setCurrentIndex(scope)
            self.scope.blockSignals(False)
            self._scope_changed(scope)
        self.filter_edit.hide()
        self.search_row.show()
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def start_search(self, force_index=False):
        text = self.search_edit.text().strip()
        whole = self.scope.currentIndex() == 1
        if not text or (not self.path and not whole):
            return
        if whole and not force_index and self._use_everything():
            self._live.stop()
            if self._ev_mode and self.search_active and text == getattr(self, "_ev_text", None):
                return                      # тот же запрос уже выполнен — список и выделение не сбрасываем
            self._ev_text = text
            self._stop_worker()
            self.results.clear()
            self._ev_mode = True
            self.search_active = True
            self.stack.setCurrentWidget(self.eresults)
            q = text + (" " if text else "") + "!\"\\$recycle.bin\\\" !\"\\system volume information\\\""
            if not self.host.show_hidden:
                q += " !attrib:H"
            self.eresults.mdl.start(q)
            self.selection_changed.emit(self)
            self._emit_status()
            return
        self._ev_mode = False
        if whole:
            import fileindex
            if fileindex.info() is None:
                if not self.host.file_index.building:
                    self.host.file_index.rebuild()
                self.host.flash("Индекс файлов ещё строится (в первый раз это пара минут). Пока можно искать «В этой папке».")
                return
        self._stop_worker()
        self.results.clear()
        self.search_active = True
        self.stack.setCurrentWidget(self.results)
        w = IndexSearchWorker(text, self.host.show_hidden) if whole else SearchWorker(self.path, text, self.host.show_hidden)
        w.found.connect(self._search_found)
        w.finished_search.connect(self._search_done)
        self._worker = w
        self._searching = True
        w.start()
        self.selection_changed.emit(self)
        self._emit_status()

    def _search_found(self, rows):
        if self.sender() is self._worker:
            self.results.add_batch(rows)
            self._emit_status()

    def _search_done(self, cancelled):
        if self.sender() is self._worker:
            self._searching = False
            self._emit_status()

    def _stop_worker(self):
        w = self._worker
        if w is not None:
            w.cancel()
            try:
                w.found.disconnect()
                w.finished_search.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._worker = None
        self._searching = False

    def close_search(self, focus=True):
        self._stop_worker()
        self._live.stop()
        self._ev_text = None
        self.search_active = False
        self._ev_mode = False
        self.search_row.hide()
        self.results.clear()
        self.eresults.clear()
        self.stack.setCurrentWidget(self.tree if self.mode == "details" else self.list)
        self.selection_changed.emit(self)
        self._emit_status()
        if focus:
            self.focus_view()

    def show_in_folder(self, path):
        """Из результатов поиска — открыть папку с файлом и выделить его."""
        self.close_search(focus=False)
        self.navigate(os.path.dirname(path), select=path)
        self.focus_view()

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.search_edit and ev.type() == QEvent.KeyPress:
            if ev.key() == Qt.Key_Escape:
                self.close_search()
                return True
            if ev.key() == Qt.Key_Down and self.search_active:
                self._res().setFocus()
                return True
        if obj is self.filter_edit and ev.type() == QEvent.KeyPress:
            if ev.key() == Qt.Key_Escape:
                self.filter_edit.clear()
                self.filter_edit.hide()
                self.focus_view()
                return True
            if ev.key() in (Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter):
                self.focus_view()
                return True
        return super().eventFilter(obj, ev)

    # ---------- выделение ----------
    def selected_paths(self):
        if self.search_active:
            return self._res().selected_paths()
        return [os.path.normpath(e.path) for e in self._selected_entries()]

    def _selected_entries(self):
        """Выделенные записи — по диапазонам строк (быстро даже при 100 000 выделенных)."""
        rows = set()
        for rng in self.tree.selectionModel().selection():
            rows.update(range(rng.top(), rng.bottom() + 1))
        data = self.model._rows
        return [data[r] for r in sorted(rows) if r < len(data)]

    def select_all(self):
        self.view().selectAll()

    def _root_index(self):
        return self.tree.rootIndex()

    def status_text(self):
        if self.search_active:
            n = self._res().topLevelItemCount()
            sel = self._res().selected_paths() if n < 20000 else []
            searching = self.eresults.mdl.loading if self._ev_mode else self._searching
            tail = "  — идёт поиск…" if searching else ""
            if self._ev_mode:
                tail += "  · Everything"
            if sel:
                return f"Найдено: {n}, выделено: {len(sel)}{tail}"
            if self._ev_mode and not n and not searching:
                return "Ничего не найдено  · Everything"
            if sel:
                return f"Найдено: {n}, выделено: {len(sel)}{tail}"
            return (f"Найдено: {n} {plural(n, 'объект', 'объекта', 'объектов')}{tail}" if n or self._searching
                    else "Ничего не найдено")
        root = self._root_index()
        total = self.model.rowCount(root)
        if self.model.loading and total == 0:
            return "Загрузка…"
        big = False
        dirs = sum(1 for e in self.model._rows if e.is_dir)
        files = total - dirs
        sel = self._selected_entries()
        if sel:
            sd = sum(1 for e in sel if e.is_dir)
            sf = len(sel) - sd
            size = sum(e.size for e in sel if not e.is_dir)
            parts = []
            if sd:
                parts.append(f"{sd} {plural(sd, 'папка', 'папки', 'папок')}")
            if sf:
                parts.append(f"{sf} {plural(sf, 'файл', 'файла', 'файлов')} ({fmt_size(size)})")
            return "Выделено: " + ", ".join(parts)
        if not self.path:
            return f"{total} {plural(total, 'диск', 'диска', 'дисков')}"
        if big:
            return f"{total} {plural(total, 'объект', 'объекта', 'объектов')}"
        parts = []
        if dirs:
            parts.append(f"{dirs} {plural(dirs, 'папка', 'папки', 'папок')}")
        if files:
            parts.append(f"{files} {plural(files, 'файл', 'файла', 'файлов')}")
        text = ", ".join(parts) if parts else "Папка пуста"
        if self._name_filter:
            text = "Найдено: " + text if parts else "Ничего не найдено"
        return text

    def _schedule_status(self, *a):
        self._status_timer.start()

    def _emit_status(self):
        self.status_changed.emit(self)

    # ---------- действия ----------
    def new_folder(self):
        base = self.path
        if not base:
            return
        if vfs.is_virtual(base):
            self.host.flash("Внутри архива папки создавать нельзя")
            return
        name = unique_name(base, "Новая папка")
        full = os.path.join(base, name)
        try:
            os.mkdir(full)
        except OSError as e:
            self.host.flash(f"Не удалось создать папку: {e.strerror}")
            return
        self.ops.on_created_folder(full)
        self._edit_when_ready(full, 40)

    # ---------- выделение по маске, размер, суммы ----------
    _last_mask = "*."

    def _row_set(self):
        rows = set()
        for rng in self.tree.selectionModel().selection():
            rows.update(range(rng.top(), rng.bottom() + 1))
        return rows

    def _select_rows(self, rows):
        from PySide6.QtCore import QItemSelection
        sm = self.tree.selectionModel()
        rows = sorted(rows)
        if not rows:
            sm.clearSelection()
            return
        sel = QItemSelection()
        start = prev = rows[0]
        for r in rows[1:] + [None]:
            if r is not None and r == prev + 1:
                prev = r
                continue
            sel.select(self.model.index(start, 0), self.model.index(prev, 0))
            start = prev = r
        sm.select(sel, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    def select_by_mask(self, mask=None):
        """Выделить файлы по маске: «*.jpg; IMG_*»; слово без * и ? ищется как часть имени."""
        import fnmatch
        import re
        if mask is None:
            from PySide6.QtWidgets import QInputDialog
            mask, ok = QInputDialog.getText(self, "Выделить по маске",
                                            "Маска (можно несколько через «;», например  *.jpg; IMG_*):",
                                            text=self._last_mask if self._last_mask != "*." else "*.")
            if not ok or not mask.strip():
                return
        self._last_mask = mask
        pats = []
        for p in re.split(r"[;,]", mask):
            p = p.strip().lower()
            if p:
                pats.append(p if any(c in p for c in "*?[") else f"*{p}*")
        rows = [i for i, e in enumerate(self.model._rows)
                if any(fnmatch.fnmatchcase(e.name.lower(), p) for p in pats)]
        self._select_rows(rows)
        self.view().setFocus()
        self.host.flash(f"Выделено по маске: {len(rows)}")
        return len(rows)

    def copy_names(self):
        """Имена выделенных файлов (по одному на строку) — в буфер обмена."""
        names = [os.path.basename(p.rstrip("\\")) or p for p in self.selected_paths()]
        if not names:
            self.host.flash("Сначала выделите файлы")
            return
        QApplication.clipboard().setText("\n".join(names))
        self.host.flash(f"Скопировано имён: {len(names)}")

    def invert_selection(self):
        cur = self._row_set()
        rows = [i for i in range(len(self.model._rows)) if i not in cur]
        self._select_rows(rows)
        self.host.flash(f"Выделено: {len(rows)}")

    def calc_size(self, paths=None):
        """Размер папок и файлов — считается в фоне, результат в строке состояния."""
        from util import folder_size
        paths = paths or self.selected_paths() or ([self.path] if self.path else [])
        paths = [p for p in paths if p and not vfs.is_virtual(p)]
        if not paths:
            self.host.flash("Размер можно посчитать только у настоящих файлов и папок на компьютере")
            return
        title = os.path.basename(paths[0].rstrip("\\")) or paths[0]
        if len(paths) > 1:
            title = f"{len(paths)} объектов"
        self.host.flash(f"Считаю размер «{title}»…", 60000)

        def done(v):
            if isinstance(v, tuple) and len(v) == 2 and v[0] == "error":
                self.host.flash("Не удалось посчитать: " + v[1])
                return
            total, files, dirs = v
            self.host.flash(f"«{title}»: {fmt_size(total)} — {files} {plural(files, 'файл', 'файла', 'файлов')}, "
                            f"{dirs} {plural(dirs, 'папка', 'папки', 'папок')}", 20000)
            self.last_size = total
        self.ops.bg(lambda: folder_size(paths), done)

    def show_hashes(self, path):
        from hashdlg import HashDialog
        dlg = HashDialog(self.window(), path)
        dlg.show()
        keep = getattr(self.host, "_dialogs", None)
        if keep is None:
            keep = self.host._dialogs = []
        keep.append(dlg)
        dlg.finished.connect(lambda *_: keep.remove(dlg) if dlg in keep else None)

    def shutdown(self):
        """Перед закрытием вкладки: остановить поиск и дождаться фоновых потоков модели."""
        try:
            self._stop_worker()
        except Exception:
            pass
        self.model.shutdown()

    def _edit_when_ready(self, full, tries):
        idx = self.model.index(full)
        if idx.isValid():
            v = self.view()
            v.setCurrentIndex(idx)
            v.scrollTo(idx)
            v.edit(idx)
        elif tries > 0:
            QTimer.singleShot(100, lambda: self._edit_when_ready(full, tries - 1))

    def rename(self):
        if self.search_active:
            self.host.flash("Из результатов поиска переименовать нельзя — откройте папку (меню «Показать в папке»)")
            return
        sel = self.selected_paths()
        if len(sel) > 1 and not any(vfs.is_virtual(p) for p in sel):
            self.bulk_rename(sel)
            return
        idx = self.view().currentIndex()
        if idx.isValid():
            self.view().edit(idx.siblingAtColumn(0))

    def bulk_rename(self, paths):
        """F2 на нескольких файлах — окно массового переименования с предпросмотром."""
        from renamedlg import RenameDialog, do_rename

        def done(pairs, errors):
            if pairs:
                for old, new in pairs:
                    self.host.tag_moved(old, new)

                def back():
                    ok, err = do_rename([(n, o) for o, n in pairs if os.path.exists(n) and not os.path.exists(o)])
                    if err:
                        self.host.flash("Не всё удалось вернуть: " + "; ".join(err)[:150])
                self.ops.push_undo("массовое переименование", back)
            self.host.flash(f"Переименовано: {len(pairs)}" + (f", ошибок: {len(errors)}" if errors else ""))
            QTimer.singleShot(200, self.model.reload)
        RenameDialog(self.window(), paths, done).exec()

    def _on_renamed(self, old, new):
        self.ops.on_renamed(old, new)
        self.host.tag_moved(old, new)

    def show_tag_menu(self, paths=None):
        """Выбор цветной метки для выделенного."""
        from PySide6.QtGui import QCursor, QPixmap, QIcon, QColor
        from fsmodel import TAG_COLORS
        paths = paths or self.selected_paths()
        if not paths:
            return
        m = QMenu(self)
        for key, (hexcol, name) in TAG_COLORS.items():
            pm = QPixmap(14, 14)
            pm.fill(QColor(hexcol))
            a = m.addAction(QIcon(pm), name)
            a.triggered.connect(lambda _=False, k=key: self.host.set_tags(paths, k))
        m.addSeparator()
        m.addAction("Убрать метку").triggered.connect(lambda: self.host.set_tags(paths, None))
        m.exec(QCursor.pos())

    def copy(self):
        self.ops.to_clipboard(self.selected_paths(), cut=False)

    def cut(self):
        self.ops.to_clipboard(self.selected_paths(), cut=True)

    def paste(self):
        sel = self.selected_paths()
        dst = self.path
        if len(sel) == 1 and vfs.isdir(sel[0]) and not vfs.is_zip_path(sel[0]):
            dst = sel[0]
        self.ops.paste(dst)

    def delete(self, permanent=False):
        self.ops.delete(self.selected_paths(), permanent)
        if self.search_active:
            QTimer.singleShot(2500, self._res().prune)
            if self._ev_mode:
                QTimer.singleShot(2800, self._live_search)      # Everything заметит удаление — обновим список

    def copy_path(self):
        sel = self.selected_paths() or ([self.path] if self.path else [])
        QApplication.clipboard().setText("\n".join(sel))
        self.host.flash("Путь скопирован")

    def open_selected(self):
        for p in self.selected_paths():
            self.open_path(p)

    def properties(self):
        sel = self.selected_paths()
        paths = sel if sel else ([self.path] if self.path else [])
        if not paths:
            return
        if any(vfs.is_virtual(p) for p in paths):
            self.host.flash("Свойства есть только у настоящих файлов на компьютере")
            return
        from propsdlg import PropsDialog
        PropsDialog(self.window(), paths).show()

    def sort_by(self, col, order=Qt.AscendingOrder):
        self.tree.sortByColumn(col, order)

    # ---------- контекстное меню ----------
    def _native_context(self, sel):
        """Родное меню Windows + наши пункты. Если не получилось — вернёт False (покажем своё меню)."""
        import nativemenu
        one_dir = len(sel) == 1 and os.path.isdir(sel[0])
        other = self.host.other_path(self)
        extras = []
        if self.search_active and len(sel) == 1:
            extras.append(("Показать в папке", lambda: self.show_in_folder(sel[0])))
        if one_dir:
            extras.append(("Открыть в новой вкладке", lambda: self.new_tab_requested.emit(sel[0])))
            if other is not None:
                extras.append(("Открыть в другой панели", lambda: self.host.open_in_other(self, sel[0])))
            extras.append(("Добавить в закладки", lambda: self.host.add_bookmark(sel[0])))
        if other is not None:
            extras.append(("Копировать в другую панель", lambda: self.ops.transfer(sel, other, True)))
            extras.append(("Переместить в другую панель", lambda: self.ops.transfer(sel, other, False)))
        extras.append(("Метка…", lambda: self.show_tag_menu(sel)))
        extras.append(("Копировать имена", self.copy_names))
        extras.append(("Посчитать размер", lambda: self.calc_size(sel)))
        if len(sel) == 1 and os.path.isfile(sel[0]):
            extras.append(("Контрольные суммы…", lambda: self.show_hashes(sel[0])))
        extras.append(("Копировать путь", self.copy_path))
        own = {
            "cut": self.cut, "copy": self.copy, "paste": self.paste, "rename": self.rename,
            "properties": self.properties,
            "open": self.open_selected, "explore": self.open_selected,
            "delete": lambda: self.delete(bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)),
        }
        shift = bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)
        try:
            return nativemenu.popup(sel, int(self.window().winId()), extras, own, shift)
        except Exception as e:
            self.host.flash(f"Родное меню недоступно, показываю своё ({e})")
            return False

    def extract_here(self, sel):
        """Распаковать выбранное из архива в папку рядом с архивом (имя_архива)."""
        z = vfs.split_zip(self.path)
        if not z:
            return
        zpath = z[0]
        dest = os.path.join(os.path.dirname(zpath), os.path.splitext(os.path.basename(zpath))[0])
        inners = [vfs.split_zip(p)[1] for p in sel if vfs.split_zip(p)] or [z[1]]
        self.host.flash("Распаковываю…", 8000)

        def done(v):
            if isinstance(v, tuple) and v and v[0] == "error":
                self.host.flash("Не удалось распаковать: " + v[1])
            else:
                self.host.flash(f"Распаковано в {dest}", 6000)
        self.ops.bg(lambda: vfs.extract(zpath, inners, dest), done)

    def _virtual_context(self, gpos, sel):
        """Меню внутри архива (родного меню Windows у таких файлов нет)."""
        m = QMenu(self)
        other = self.host.other_path(self)

        def add(text, fn, enabled=True):
            a = m.addAction(text)
            a.setEnabled(enabled)
            a.triggered.connect(lambda _=False: fn())

        if sel:
            add("Открыть", self.open_selected)
            add("Копировать (в буфер)", self.copy)
            if other and not vfs.is_virtual(other):
                add("Скопировать в другую панель", lambda: self.ops.transfer(sel, other, True))
            add("Распаковать в папку рядом с архивом", lambda: self.extract_here(sel))
            m.addSeparator()
            add("Копировать путь", self.copy_path)
        else:
            add("Распаковать всё в папку рядом с архивом", lambda: self.extract_here([]))
            add("Обновить", self.refresh)
        m.exec(gpos)

    def show_context(self, gpos, on_item):
        sel = self.selected_paths() if on_item else []
        if self.search_active and not sel:
            return
        if vfs.is_virtual(self.path) or any(vfs.is_virtual(p) for p in sel):
            self._virtual_context(gpos, sel)
            return
        same_parent =len({os.path.dirname(p).lower() for p in sel}) <= 1
        if sel and same_parent and self.host.settings.get("native_menu", True) and self._native_context(sel):
            return
        m = QMenu(self)
        can_paste = self.ops.can_paste() and bool(self.path or (len(sel) == 1 and os.path.isdir(sel[0])))

        def add(text, fn, enabled=True, shortcut=None):
            a = QAction(text + (f"\t{shortcut}" if shortcut else ""), m)
            a.setEnabled(enabled)
            a.triggered.connect(lambda _=False: fn())
            m.addAction(a)
            return a

        other = self.host.other_path(self)
        if sel:
            one_dir = len(sel) == 1 and os.path.isdir(sel[0])
            add("Открыть", self.open_selected, shortcut="Enter")
            if self.search_active and len(sel) == 1:
                add("Показать в папке", lambda: self.show_in_folder(sel[0]))
            if one_dir:
                add("Открыть в новой вкладке", lambda: self.new_tab_requested.emit(sel[0]))
                add("Открыть в другой панели", lambda: self.host.open_in_other(self, sel[0]))
            if len(sel) == 1 and not os.path.isdir(sel[0]):
                add("Открыть с помощью…", lambda: sh.open_with(sel[0]))
                add("Показать в Проводнике Windows", lambda: sh.reveal(sel[0]))
            m.addSeparator()
            add("Вырезать", self.cut, shortcut="Ctrl+X")
            add("Копировать", self.copy, shortcut="Ctrl+C")
            add("Вставить", self.paste, can_paste and one_dir, "Ctrl+V")
            if other is not None:
                m.addSeparator()
                add("Копировать в другую панель", lambda: self.ops.transfer(sel, other, True))
                add("Переместить в другую панель", lambda: self.ops.transfer(sel, other, False))
            m.addSeparator()
            add("Копировать путь", self.copy_path)
            add("Копировать имена", self.copy_names)
            add("Метка…", lambda: self.show_tag_menu(sel))
            add("Посчитать размер", lambda: self.calc_size(sel))
            if len(sel) == 1 and os.path.isfile(sel[0]):
                add("Контрольные суммы…", lambda: self.show_hashes(sel[0]))
            add("Переименовать", self.rename, len(sel) == 1, "F2")
            add("В корзину", self.delete, shortcut="Del")
            add("Удалить навсегда", lambda: self.delete(True), shortcut="Shift+Del")
            m.addSeparator()
            if one_dir:
                add("Добавить в закладки", lambda: self.host.add_bookmark(sel[0]))
            add("Свойства", self.properties, shortcut="Alt+Enter")
        else:
            add("Создать папку", self.new_folder, bool(self.path), "Ctrl+Shift+N")
            add("Вставить", self.paste, can_paste, "Ctrl+V")
            m.addSeparator()
            sort = m.addMenu("Сортировать")
            for col, name in ((0, "По имени"), (1, "По размеру"), (2, "По типу"), (3, "По дате")):
                a = sort.addAction(name)
                a.triggered.connect(lambda _=False, c=col: self.sort_by(c))
            sort.addSeparator()
            sort.addAction("По возрастанию").triggered.connect(
                lambda: self.sort_by(self.tree.header().sortIndicatorSection(), Qt.AscendingOrder))
            sort.addAction("По убыванию").triggered.connect(
                lambda: self.sort_by(self.tree.header().sortIndicatorSection(), Qt.DescendingOrder))
            vm = m.addMenu("Вид")
            for mode, name in (("icons", "Значки"), ("compact", "Компактно"), ("details", "Подробно")):
                a = vm.addAction(name)
                a.setCheckable(True)
                a.setChecked(self.mode == mode)
                a.triggered.connect(lambda _=False, md=mode: self.set_mode(md))
            add("Обновить", self.refresh, shortcut="F5")
            m.addSeparator()
            add("Выделить по маске…", self.select_by_mask, shortcut="Ctrl+S")
            add("Инвертировать выделение", self.invert_selection, shortcut="Ctrl+Shift+I")
            if self.path:
                add("Посчитать размер папки", lambda: self.calc_size([self.path]))
                add("Открыть терминал здесь", lambda: sh.open_terminal(self.path))
                add("Добавить папку в закладки", lambda: self.host.add_bookmark(self.path))
                add("Свойства", self.properties)
        m.exec(gpos)
