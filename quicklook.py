"""Быстрый просмотр по пробелу: картинки, текст, видео/PDF/музыка (миниатюра Windows), папки."""
import os
from datetime import datetime

from PySide6.QtCore import Qt, QRectF, QRunnable, QThreadPool, QObject, Signal, QFileInfo, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QPixmap, QImage, QImageReader, QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QStackedWidget,
                               QFileIconProvider)

import theme
from util import fmt_size, plural

IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tif", ".tiff", ".jfif")
SHELL_EXT = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv", ".mpg", ".mpeg", ".3gp", ".pdf",
             ".svg", ".psd", ".heic", ".heif", ".avif", ".mp3", ".flac", ".m4a", ".pptx", ".docx", ".xlsx", ".epub")
TEXT_EXT = (".txt", ".md", ".py", ".json", ".js", ".html", ".css", ".log", ".ini", ".cfg", ".bat", ".ps1", ".xml",
            ".csv", ".yaml", ".yml", ".toml", ".c", ".cpp", ".h", ".java", ".cs", ".sh", ".srt", ".smali", ".conf",
            ".properties", ".gradle", ".kt", ".rs", ".go", ".ts", ".tsx", ".jsx", ".sql", ".reg", ".inf", ".url")


class _Sig(QObject):
    done = Signal(int, QImage)


class _Job(QRunnable):
    def __init__(self, sig, token, path):
        super().__init__()
        self.sig, self.token, self.path = sig, token, path

    def run(self):
        img = QImage()
        try:
            import ctypes
            ctypes.windll.ole32.CoInitialize(None)
            try:
                from winthumb import shell_thumbnail
                img = shell_thumbnail(self.path, 1024)
            finally:
                ctypes.windll.ole32.CoUninitialize()
        except Exception:
            img = QImage()
        self.sig.done.emit(self.token, img)


class QuickLook(QWidget):
    def __init__(self, host):
        super().__init__(host, Qt.Tool | Qt.FramelessWindowHint)
        self.host = host
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._token = 0
        self._path = None
        self._sig = _Sig()
        self._sig.done.connect(self._thumb_done)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._pm = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(34, 34)
        head.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel()
        f = QFont(self.title.font())
        f.setPointSizeF(f.pointSizeF() + 2)
        f.setBold(True)
        self.title.setFont(f)
        self.sub = QLabel()
        col.addWidget(self.title)
        col.addWidget(self.sub)
        head.addLayout(col, 1)
        self.hint = QLabel("Пробел или Esc — закрыть   ·   ←/→/↑/↓ — другой файл   ·   Enter — открыть")
        head.addWidget(self.hint)
        lay.addLayout(head)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setFocusPolicy(Qt.NoFocus)
        self.note = QLabel()
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setWordWrap(True)
        for w in (self.image, self.text, self.note):
            self.stack.addWidget(w)
        self._icons = QFileIconProvider()
        self._update_style()

    def _update_style(self):
        c = theme.colors()
        self.hint.setStyleSheet(f"color: {c['dim']};")
        self.sub.setStyleSheet(f"color: {c['dim']};")
        self.title.setStyleSheet(f"color: {c['text']};")
        self.note.setStyleSheet(f"color: {c['dim']}; font-size: 15px;")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        light = theme.current_name() in ("light", "glass_light")
        bg = QColor(246, 248, 252, 245) if light else QColor(24, 27, 36, 244)
        p.setBrush(bg)
        p.setPen(QPen(QColor(0, 0, 0, 40) if light else QColor(255, 255, 255, 45), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)

    # ---------- показ ----------
    def show_for(self, path):
        self._update_style()
        self._path = path
        self._token += 1
        w, h = self.host.width(), self.host.height()
        self.resize(int(w * 0.74), int(h * 0.80))
        g = self.host.frameGeometry()
        self.move(g.x() + (g.width() - self.width()) // 2, g.y() + (g.height() - self.height()) // 2 + 14)
        fi = QFileInfo(path)
        self.title.setText(fi.fileName() or path)
        self.icon.setPixmap(self._icons.icon(fi).pixmap(32))
        info = []
        try:
            st = os.stat(path)
            if os.path.isfile(path):
                info.append(fmt_size(st.st_size))
            info.append(datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M"))
        except OSError:
            pass
        low = path.lower()
        if os.path.isdir(path):
            self._show_folder(path, info)
        elif low.endswith(IMG_EXT):
            self._show_image(path, info)
        elif low.endswith(SHELL_EXT):
            self.note.setText("Загрузка миниатюры…")
            self.stack.setCurrentWidget(self.note)
            self._pool.start(_Job(self._sig, self._token, path))
        elif low.endswith(TEXT_EXT) or self._looks_text(path):
            self._show_text(path)
        else:
            self.note.setText("Для этого типа файла предпросмотра нет.\nEnter — открыть в программе по умолчанию.")
            self.stack.setCurrentWidget(self.note)
        self.sub.setText("  ·  ".join(info + [self._icons.type(fi) or ""]))
        if not self.isVisible():
            self.show()

    def _looks_text(self, path):
        try:
            if os.path.getsize(path) > 3_000_000:
                return False
            with open(path, "rb") as f:
                head = f.read(4096)
            return b"\x00" not in head and bool(head)
        except OSError:
            return False

    def _show_folder(self, path, info):
        try:
            with os.scandir(path) as it:
                names = []
                dirs = files = 0
                for e in it:
                    if len(names) < 60:
                        names.append(("📁 " if e.is_dir() else "   ") + e.name)
                    if e.is_dir():
                        dirs += 1
                    else:
                        files += 1
            info.append(f"{dirs} {plural(dirs, 'папка', 'папки', 'папок')}, {files} {plural(files, 'файл', 'файла', 'файлов')}")
            self.text.setPlainText("\n".join(sorted(names)))
        except OSError:
            self.text.setPlainText("Нет доступа к папке")
        self.stack.setCurrentWidget(self.text)

    def _show_image(self, path, info):
        r = QImageReader(path)
        r.setAutoTransform(True)
        sz = r.size()
        if sz.isValid():
            info.append(f"{sz.width()}×{sz.height()}")
            box = self.stack.size()
            tgt = QSize(sz)
            tgt.scale(max(200, box.width() - 8), max(150, box.height() - 8), Qt.KeepAspectRatio)
            if tgt.width() < sz.width():
                r.setScaledSize(tgt)
        img = r.read()
        if img.isNull():
            self.note.setText("Не удалось показать картинку")
            self.stack.setCurrentWidget(self.note)
        else:
            self._pm = QPixmap.fromImage(img)
            self.image.setPixmap(self._pm)
            self.stack.setCurrentWidget(self.image)

    def _show_text(self, path):
        try:
            with open(path, "rb") as f:
                raw = f.read(300_000)
            for enc in ("utf-8-sig", "cp1251", "latin-1"):
                try:
                    self.text.setPlainText(raw.decode(enc))
                    break
                except UnicodeDecodeError:
                    continue
        except OSError:
            self.text.setPlainText("Не удалось прочитать файл")
        self.stack.setCurrentWidget(self.text)

    def _thumb_done(self, token, img):
        if token != self._token:
            return
        if img.isNull():
            self.note.setText("Для этого файла Windows не умеет делать картинку.\nEnter — открыть в программе по умолчанию.")
            self.stack.setCurrentWidget(self.note)
            return
        box = self.stack.size()
        self._pm = QPixmap.fromImage(img).scaled(max(200, box.width() - 8), max(150, box.height() - 8),
                                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image.setPixmap(self._pm)
        self.stack.setCurrentWidget(self.image)

    def hide_it(self):
        self._token += 1
        self.hide()
