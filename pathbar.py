"""Строка пути: кликабельные части (как в Dolphin), по щелчку на пустом месте — ввод текстом."""
import os

from PySide6.QtCore import Qt, Signal, QDir, QEvent, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QStackedWidget, QWidget, QHBoxLayout, QToolButton, QLineEdit, QMenu,
                               QCompleter, QFileSystemModel, QSizePolicy)

from ui import G, icon_font
from util import norm_path


def split_path(path):
    """[(подпись, путь), …] от «Этот компьютер» до текущей папки."""
    parts = [("Этот компьютер", "")]
    if not path:
        return parts
    drive, rest = os.path.splitdrive(path)
    if drive.startswith("\\\\"):          # сетевой путь
        acc = drive
        parts.append((drive, acc + "\\"))
    else:
        acc = drive + "\\"
        parts.append((drive, acc))
    for name in [p for p in rest.replace("/", "\\").split("\\") if p]:
        acc = os.path.join(acc, name)
        parts.append((name, acc))
    return parts


class _CrumbButton(QToolButton):
    """Кнопка части пути: на неё можно бросить файлы — они попадут в эту папку."""
    dropped = Signal(list, bool, bool)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            m = e.keyboardModifiers()
            self.dropped.emit(urls, bool(m & Qt.ControlModifier), bool(m & Qt.ShiftModifier))
            e.setDropAction(Qt.CopyAction)
            e.accept()


class _Crumbs(QWidget):
    def __init__(self, bar):
        super().__init__()
        self.bar = bar
        self.setObjectName("crumbs")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(4, 0, 4, 0)
        self.lay.setSpacing(0)
        self.groups = []
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setCursor(Qt.IBeamCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.bar.begin_edit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def build(self, path):
        for g in self.groups:
            self.lay.removeWidget(g)
            g.hide()
            g.setParent(None)
            g.deleteLater()
        self.groups = []
        while self.lay.count():
            self.lay.takeAt(0)
        parts = split_path(path)
        for i, (label, p) in enumerate(parts):
            g = QWidget()
            g.setCursor(Qt.ArrowCursor)
            g.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)   # не сжимать — иначе надписи налезают
            h = QHBoxLayout(g)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(0)
            b = _CrumbButton()
            b.setText(label)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, p=p: self.bar.navigate.emit(p))
            if p:
                b.dropped.connect(lambda urls, c, s, p=p: self.bar.files_dropped.emit(urls, p, c, s))
            if i == len(parts) - 1:
                f = b.font()
                f.setBold(True)
                b.setFont(f)
            h.addWidget(b)
            ch = QToolButton()
            ch.setText(G["chev"])
            ch.setFont(icon_font(10))
            ch.setProperty("chev", "true")
            ch.setPopupMode(QToolButton.InstantPopup)
            m = QMenu(ch)
            m.aboutToShow.connect(lambda m=m, p=p: self._fill_menu(m, p))
            ch.setMenu(m)
            h.addWidget(ch)
            self.lay.addWidget(g)
            self.groups.append(g)
        self.lay.addStretch(1)
        self._fit()
        QTimer.singleShot(0, self._fit)
        QTimer.singleShot(80, self._fit)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._fit)

    def _fit(self):
        if not self.groups:
            return
        for g in self.groups:
            g.show()
            g.ensurePolished()
            for b in g.findChildren(QToolButton):
                b.ensurePolished()
        self.lay.activate()
        avail = self.width() - 16
        total = sum(g.sizeHint().width() for g in self.groups)
        i = 0
        while total > avail and i < len(self.groups) - 1:
            total -= self.groups[i].sizeHint().width()
            self.groups[i].hide()
            i += 1

    def _fill_menu(self, menu, path):
        menu.clear()
        names = []
        try:
            if not path:
                from PySide6.QtCore import QStorageInfo
                for v in QStorageInfo.mountedVolumes():
                    names.append((v.rootPath().replace("/", "\\"), v.rootPath().replace("/", "\\")))
            else:
                with os.scandir(path) as it:
                    for e in it:
                        try:
                            if e.is_dir() and not e.name.startswith(("$", ".")):
                                names.append((e.name, e.path))
                        except OSError:
                            pass
        except OSError:
            pass
        names.sort(key=lambda x: x[0].lower())
        if not names:
            a = menu.addAction("(нет вложенных папок)")
            a.setEnabled(False)
            return
        for label, p in names[:400]:
            a = QAction(label, menu)
            a.triggered.connect(lambda _=False, p=p: self.bar.navigate.emit(p))
            menu.addAction(a)


class PathBar(QStackedWidget):
    navigate = Signal(str)
    files_dropped = Signal(list, str, bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.crumbs = _Crumbs(self)
        self.edit = QLineEdit()
        self.addWidget(self.crumbs)
        self.addWidget(self.edit)
        cm = QFileSystemModel(self)
        cm.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)
        cm.setRootPath("")
        comp = QCompleter(cm, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.edit.setCompleter(comp)
        self.edit.returnPressed.connect(self._commit)
        self.edit.installEventFilter(self)
        self._path = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def set_path(self, path):
        self._path = path
        self.crumbs.build(path)
        self.setCurrentIndex(0)

    def begin_edit(self):
        self.edit.setText(self._path)
        self.setCurrentIndex(1)
        self.edit.setFocus()
        self.edit.selectAll()

    def _end_edit(self):
        self.setCurrentIndex(0)

    def _commit(self):
        text = os.path.expandvars(self.edit.text().strip().strip('"'))
        self._end_edit()
        if not text or text.lower() in ("этот компьютер", "this pc", "компьютер"):
            self.navigate.emit("")
        else:
            self.navigate.emit(norm_path(text))

    def eventFilter(self, obj, ev):
        if obj is self.edit:
            if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
                self._end_edit()
                self.parent().setFocus() if self.parent() else None
                return True
            if ev.type() == QEvent.FocusOut and self.currentIndex() == 1:
                popup = self.edit.completer().popup() if self.edit.completer() else None
                if popup is None or not popup.isVisible():
                    self._end_edit()
        return super().eventFilter(obj, ev)
