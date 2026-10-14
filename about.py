"""Окно «О программе» и «Что нового»."""
import os
import platform
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser)

import settings
import version


def base_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def changelog_text():
    try:
        with open(os.path.join(base_dir(), "CHANGELOG.md"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "# Журнал изменений\n\nФайл CHANGELOG.md не найден."


def latest_section(text):
    """Только самая свежая версия из журнала."""
    parts = text.split("\n## ")
    if len(parts) < 2:
        return text
    return "## " + parts[1].split("\n## ")[0]


class ChangelogDialog(QDialog):
    def __init__(self, parent=None, only_latest=False):
        super().__init__(parent)
        self.setWindowTitle("Что нового в Orca")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        text = changelog_text()
        view.setMarkdown(latest_section(text) if only_latest else text)
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        b = QPushButton("Понятно")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("О программе")
        self.setFixedWidth(460)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        head = QHBoxLayout()
        pm = QPixmap(os.path.join(base_dir(), "icon.png"))
        icon = QLabel()
        if not pm.isNull():
            icon.setPixmap(pm.scaled(84, 84, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(icon)
        col = QVBoxLayout()
        title = QLabel(version.APP_NAME)
        f = QFont(title.font())
        f.setPointSize(f.pointSize() + 10)
        f.setBold(True)
        title.setFont(f)
        col.addWidget(title)
        col.addWidget(QLabel(f"Версия {version.VERSION}  ·  {version.RELEASE_DATE}"))
        col.addWidget(QLabel("Быстрый файловый менеджер для Windows\nв духе Dolphin (KDE)"))
        head.addLayout(col, 1)
        lay.addLayout(head)
        try:
            from PySide6 import __version__ as pyside_v
        except Exception:
            pyside_v = "?"
        info = QLabel(f"Qt / PySide6 {pyside_v}  ·  Python {platform.python_version()}\n"
                      f"Windows {platform.version()}\n"
                      f"Настройки и журналы: {settings.DIR}")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.setWordWrap(True)
        lay.addWidget(info)
        row = QHBoxLayout()
        b1 = QPushButton("Что нового")
        b1.clicked.connect(lambda: ChangelogDialog(self).exec())
        b2 = QPushButton("Открыть папку с журналами")
        b2.clicked.connect(self._open_dir)
        b3 = QPushButton("Закрыть")
        b3.clicked.connect(self.accept)
        for b in (b1, b2):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b3)
        lay.addLayout(row)

    def _open_dir(self):
        try:
            os.makedirs(settings.DIR, exist_ok=True)
            os.startfile(settings.DIR)
        except OSError:
            pass
