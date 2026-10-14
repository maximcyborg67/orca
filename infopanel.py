"""Панель сведений справа: миниатюра, размер, дата, начало текстового файла."""
import os
from datetime import datetime

from PySide6.QtCore import Qt, QFileInfo, QSize
from PySide6.QtGui import QPixmap, QImageReader
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QPlainTextEdit, QFileIconProvider

from util import fmt_size, plural

TEXT_EXT = (".txt", ".md", ".py", ".json", ".js", ".html", ".css", ".log", ".ini", ".cfg", ".bat", ".ps1",
            ".xml", ".csv", ".yaml", ".yml", ".toml", ".c", ".cpp", ".h", ".java", ".cs", ".sh", ".srt")
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".jfif")


class InfoPanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("infopanel")
        self.setMinimumWidth(220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setMinimumHeight(150)
        lay.addWidget(self.pic)
        self.name = QLabel()
        self.name.setWordWrap(True)
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f = self.name.font()
        f.setBold(True)
        self.name.setFont(f)
        lay.addWidget(self.name)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.RichText)
        lay.addWidget(self.details)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.hide()
        lay.addWidget(self.text, 1)
        lay.addStretch(0)
        self._icons = QFileIconProvider()
        self.show_paths([], "")

    def show_paths(self, paths, folder):
        self.text.hide()
        self.pic.clear()
        if not paths:
            self.pic.setPixmap(self._icons.icon(QFileInfo(folder)).pixmap(72) if folder else QPixmap())
            self.name.setText(os.path.basename(folder.rstrip("\\")) or folder or "Этот компьютер")
            self.details.setText("<span style='color:gray'>Выберите файл — здесь появятся сведения о нём</span>")
            return
        if len(paths) > 1:
            n = len(paths)
            size = 0
            for p in paths:
                try:
                    if os.path.isfile(p):
                        size += os.path.getsize(p)
                except OSError:
                    pass
            self.pic.setPixmap(self._icons.icon(QFileIconProvider.File).pixmap(72))
            self.name.setText(f"{n} {plural(n, 'объект', 'объекта', 'объектов')}")
            self.details.setText(f"Общий размер файлов: {fmt_size(size)}")
            return
        p = paths[0]
        fi = QFileInfo(p)
        self.name.setText(fi.fileName() or p)
        rows = [("Тип", self._icons.type(fi))]
        try:
            st = os.stat(p)
            if os.path.isfile(p):
                rows.append(("Размер", f"{fmt_size(st.st_size)} ({st.st_size:,} Б)".replace(",", " ")))
            rows.append(("Изменён", datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M")))
            rows.append(("Создан", datetime.fromtimestamp(st.st_ctime).strftime("%d.%m.%Y %H:%M")))
        except OSError:
            pass
        low = p.lower()
        pm = None
        if os.path.isfile(p) and low.endswith(IMG_EXT):
            r = QImageReader(p)
            r.setAutoTransform(True)
            sz = r.size()
            if sz.isValid():
                rows.append(("Размер кадра", f"{sz.width()}×{sz.height()}"))
                tgt = QSize(sz)
                tgt.scale(320, 240, Qt.KeepAspectRatio)
                if tgt.width() < sz.width():
                    r.setScaledSize(tgt)
                img = r.read()
                if not img.isNull():
                    pm = QPixmap.fromImage(img)
        if pm is None:
            pm = self._icons.icon(fi).pixmap(72)
        self.pic.setPixmap(pm)
        if os.path.isdir(p):
            try:
                with os.scandir(p) as it:
                    n = sum(1 for _ in zip(range(5000), it))
                rows.append(("Содержит", f"{n}{'+' if n >= 5000 else ''} {plural(n, 'объект', 'объекта', 'объектов')}"))
            except OSError:
                pass
        self.details.setText("".join(f"<p style='margin:2px 0'><span style='color:gray'>{k}</span><br>{v}</p>"
                                     for k, v in rows))
        if os.path.isfile(p) and low.endswith(TEXT_EXT):
            try:
                with open(p, "rb") as f:
                    raw = f.read(6000)
                for enc in ("utf-8-sig", "cp1251"):
                    try:
                        self.text.setPlainText(raw.decode(enc))
                        break
                    except UnicodeDecodeError:
                        continue
                self.text.show()
            except OSError:
                pass
