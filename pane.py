"""Панель с вкладками (в окне их может быть две — слева и справа)."""
from PySide6.QtCore import Qt, Signal, QFileInfo
from PySide6.QtWidgets import QTabWidget, QTabBar, QFileIconProvider

from folderview import FolderView
from ui import G, glyph_button


class TabBar(QTabBar):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        i = self.tabAt(e.position().toPoint())
        if e.mimeData().hasUrls() and i >= 0 and self.pane.widget(i).path:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        i = self.tabAt(e.position().toPoint())
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if i >= 0 and urls and self.pane.widget(i).path:
            mods = e.keyboardModifiers()
            ops = self.pane.host.ops
            target = self.pane.widget(i).path
            ops.transfer(urls, target, ops.default_copy(urls, target, bool(mods & Qt.ControlModifier),
                                                         bool(mods & Qt.ShiftModifier)))
            e.setDropAction(Qt.CopyAction)
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton:
            i = self.tabAt(e.position().toPoint())
            if i >= 0:
                self.tabCloseRequested.emit(i)
                return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.tabAt(e.position().toPoint()) < 0:
            self.pane.new_tab_requested.emit()
            return
        super().mouseDoubleClickEvent(e)


class Pane(QTabWidget):
    new_tab_requested = Signal()
    last_tab_closed = Signal(object)

    def __init__(self, host, paths, mode):
        super().__init__()
        self.host = host
        self._icons = QFileIconProvider()
        self.setTabBar(TabBar(self))
        self.setDocumentMode(True)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.ElideRight)
        plus = glyph_button(G["newtab"], "Новая вкладка (Ctrl+T)", 14)
        plus.clicked.connect(lambda: self.add_tab(self.current_path() or "", switch=True))
        self.setCornerWidget(plus, Qt.TopRightCorner)
        self.tabCloseRequested.connect(self.close_tab)
        self.new_tab_requested.connect(lambda: self.add_tab(self.current_path() or ""))
        for p in paths or [""]:
            self.add_tab(p, mode, switch=False)
        self.setCurrentIndex(0)

    def current_folder(self):
        return self.currentWidget()

    def current_path(self):
        f = self.currentWidget()
        return f.path if f else ""

    def folders(self):
        return [self.widget(i) for i in range(self.count())]

    def add_tab(self, path, mode=None, switch=True):
        mode = mode or self.host.mode
        f = FolderView(self.host, path, mode)
        f.path_changed.connect(self._title_changed)
        f.new_tab_requested.connect(lambda p: self.add_tab(p, switch=True))
        self.host.wire(f)
        i = self.addTab(f, f.title())
        self._title_changed(f)
        if switch:
            self.setCurrentIndex(i)
            f.focus_view()
        return f

    def close_tab(self, i):
        if self.count() <= 1:
            self.last_tab_closed.emit(self)
            return
        w = self.widget(i)
        self.host.remember_closed_tab(w.path)
        self.removeTab(i)
        w.shutdown()               # остановить фоновое чтение папки и поиск, прежде чем удалять вкладку
        w.deleteLater()

    def _title_changed(self, f):
        i = self.indexOf(f)
        if i >= 0:
            self.setTabText(i, f.title().replace("&", "&&"))
            self.setTabToolTip(i, f.path or "Этот компьютер")
            self.setTabIcon(i, self._icons.icon(QFileInfo(f.path)) if f.path else
                            self._icons.icon(QFileIconProvider.Computer))

    def next_tab(self, step=1):
        if self.count():
            self.setCurrentIndex((self.currentIndex() + step) % self.count())
