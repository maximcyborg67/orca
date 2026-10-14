"""Быстрые команды (Ctrl+Shift+P): печатаете часть названия действия — Enter запускает его."""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


def collect(win):
    """[(название, горячая клавиша, QAction)] — все действия окна с понятными названиями."""
    out, seen = [], set()
    for a in win.actions():
        title = a.toolTip() or a.text()
        title = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()          # «Новая вкладка  (Ctrl+T)» -> «Новая вкладка»
        if not title or len(title) <= 1 or title in seen or not a.isEnabled():
            continue
        seen.add(title)
        out.append((title, a.shortcut().toString(), a))
    return sorted(out, key=lambda x: x[0].lower())


class Palette(QDialog):
    def __init__(self, win):
        super().__init__(win, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.resize(520, 380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Что сделать? Например: вкладка, поиск, дубликаты, метка…")
        lay.addWidget(self.edit)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.items = collect(win)
        self.edit.textChanged.connect(self._fill)
        self.edit.installEventFilter(self)
        self.list.itemActivated.connect(self._run)
        self._fill("")
        g = win.frameGeometry()
        self.move(g.x() + (g.width() - self.width()) // 2, g.y() + 90)

    def _fill(self, text):
        words = text.lower().split()
        self.list.clear()
        for title, key, act in self.items:
            if all(w in title.lower() for w in words):
                it = QListWidgetItem(f"{title}" + (f"      {key}" if key else ""))
                it.setData(Qt.UserRole, act)
                self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run(self, item):
        act = item.data(Qt.UserRole)
        self.accept()
        if act is not None:
            act.trigger()

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.edit and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                r = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, r)))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                if self.list.currentItem():
                    self._run(self.list.currentItem())
                return True
            if k == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, ev)

    def showEvent(self, e):
        super().showEvent(e)
        self.edit.setFocus()
