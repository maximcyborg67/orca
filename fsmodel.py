"""Модель списка файлов: своя, быстрая (папка читается в фоне, сортировка по числам, слежение за изменениями),
плюс миниатюры (картинки — Qt, видео/PDF/музыка — средствами Windows) и безопасное переименование."""
import os
import re
import time
from collections import OrderedDict

from PySide6.QtCore import (Qt, QObject, Signal, QRunnable, QThreadPool, QThread, QAbstractTableModel, QModelIndex,
                            QFileSystemWatcher, QTimer, QMimeData, QUrl, QFileInfo, QDateTime, QStorageInfo)
from PySide6.QtGui import QImage, QImageReader, QPixmap, QIcon
from PySide6.QtWidgets import QFileIconProvider

from util import fmt_size

IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tif", ".tiff", ".jfif")
THUMB_PX = 192
# то, для чего просим миниатюру у Windows (видео, документы, обложки музыки…)
SHELL_EXT = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv", ".mpg", ".mpeg", ".ts", ".3gp",
             ".pdf", ".svg", ".psd", ".heic", ".heif", ".avif", ".cr2", ".nef", ".arw", ".dng",
             ".mp3", ".flac", ".m4a", ".pptx", ".docx", ".xlsx", ".epub")
MAX_QUEUE = 300      # не копим очередь миниатюр при быстрой прокрутке огромной папки


# ====================== миниатюры ======================
class _Job(QRunnable):
    def __init__(self, owner, path):
        super().__init__()
        self.owner = owner
        self.path = path

    def run(self):
        img = QImage()
        if self.path.lower().endswith(SHELL_EXT):
            import ctypes
            ctypes.windll.ole32.CoInitialize(None)
            try:
                from winthumb import shell_thumbnail
                img = shell_thumbnail(self.path, THUMB_PX)
            except Exception:
                img = QImage()
            finally:
                ctypes.windll.ole32.CoUninitialize()
            self.owner._loaded.emit(self.path, img)
            return
        try:
            r = QImageReader(self.path)
            r.setAutoTransform(True)
            sz = r.size()
            if sz.isValid():
                if sz.width() > THUMB_PX or sz.height() > THUMB_PX:
                    sz.scale(THUMB_PX, THUMB_PX, Qt.KeepAspectRatio)
                    r.setScaledSize(sz)
                img = r.read()
        except Exception:
            img = QImage()
        self.owner._loaded.emit(self.path, img)


class Thumbs(QObject):
    """Миниатюры грузятся в фоне; пока не готовы — обычный значок."""
    ready = Signal(str)
    _loaded = Signal(str, QImage)

    def __init__(self):
        super().__init__()
        self.cache = OrderedDict()
        self.pending = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self._loaded.connect(self._on_loaded)

    def get(self, path):
        ic = self.cache.get(path)
        if ic is not None:
            return ic or None
        if path not in self.pending and len(self.pending) < MAX_QUEUE:
            self.pending.add(path)
            self.pool.start(_Job(self, path))
        return None

    def _on_loaded(self, path, img):
        self.pending.discard(path)
        if img.isNull():
            self.cache[path] = False
        else:
            self.cache[path] = QIcon(QPixmap.fromImage(img))
            self.ready.emit(path)
        while len(self.cache) > 3000:
            self.cache.popitem(last=False)


THUMBS = None


def thumbs():
    global THUMBS
    if THUMBS is None:
        THUMBS = Thumbs()
    return THUMBS


class ShellInfo(QObject):
    """Значки файлов и названия типов достаются у Windows в ФОНЕ: чтение настоящего значка программы с холодного
    диска (с проверкой антивирусом) занимает секунды, и раньше из-за этого окно зависало при входе в папку."""
    icon_ready = Signal()
    type_ready = Signal()
    _res = Signal(str, str, object)

    def __init__(self):
        super().__init__()
        import queue
        import threading
        self.icons = {}
        self.types = {}
        self._pending = set()
        self._q = queue.Queue()
        self._res.connect(self._on_res)
        threading.Thread(target=self._run, daemon=True).start()

    def icon(self, key, path):
        v = self.icons.get(key)
        if v is None and ("i", key) not in self._pending:
            self._pending.add(("i", key))
            self._q.put(("i", key, path))
        return v or None

    def type(self, ext, path):
        v = self.types.get(ext)
        if v is None and ("t", ext) not in self._pending:
            self._pending.add(("t", ext))
            self._q.put(("t", ext, path))
        return v or None

    def _run(self):
        import ctypes
        ctypes.windll.ole32.CoInitialize(None)
        provider = QFileIconProvider()
        while True:
            kind, key, path = self._q.get()
            try:
                if kind == "i":
                    from winthumb import shell_icon
                    self._res.emit("i", key, shell_icon(path, 128))
                else:
                    self._res.emit("t", key, provider.type(QFileInfo(path)))
            except Exception:
                self._res.emit(kind, key, None)

    def _on_res(self, kind, key, payload):
        self._pending.discard((kind, key))
        if kind == "i":
            ok = payload is not None and not payload.isNull()
            self.icons[key] = QIcon(QPixmap.fromImage(payload)) if ok else False
            if len(self.icons) > 5000:
                self.icons.pop(next(iter(self.icons)))
            self.icon_ready.emit()
        else:
            self.types[key] = payload or ""
            self.type_ready.emit()


SHELL = None


def shellinfo():
    global SHELL
    if SHELL is None:
        SHELL = ShellInfo()
    return SHELL


# ====================== записи и сортировка ======================
_split = re.compile(r"(\d+)").split


def nat_key(name):
    """«файл2» раньше «файл10»; регистр не важен."""
    return [(0, int(p), "") if (p.isdigit() and p.isascii()) else (1, 0, p) for p in _split(name.casefold()) if p]


class Entry:
    __slots__ = ("name", "path", "is_dir", "size", "mtime", "hidden", "nkey", "ext", "label", "drive", "virtual")

    def __init__(self, name, path, is_dir, size, mtime, hidden, label=None, drive=False, virtual=False):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.mtime = mtime
        self.hidden = hidden
        self.nkey = nat_key(name)
        self.ext = "" if is_dir else os.path.splitext(name)[1].lower()
        self.label = label
        self.drive = drive
        self.virtual = virtual


def sort_entries(entries, col, order):
    """Папки всегда выше файлов; внутри — по выбранному столбцу."""
    desc = (order == Qt.DescendingOrder)
    dirs = [e for e in entries if e.is_dir]
    files = [e for e in entries if not e.is_dir]
    if col == 1:
        kd, kf = (lambda e: e.nkey), (lambda e: (e.size, e.nkey))
    elif col == 2:
        kd, kf = (lambda e: e.nkey), (lambda e: (e.ext, e.nkey))
    elif col == 3:
        kd = kf = (lambda e: (e.mtime, e.nkey))
    else:
        kd = kf = (lambda e: e.nkey)
    dirs.sort(key=kd, reverse=desc)
    files.sort(key=kf, reverse=desc)
    entries[:] = dirs + files


class ScanWorker(QThread):
    """Читает папку в отдельном потоке — окно не зависает даже на 100 000 файлов."""
    done = Signal(int, list, str)

    def __init__(self, token, path, sort):
        super().__init__()
        self.token, self.path, self.sort = token, path, sort

    def run(self):
        entries, err = [], ""
        try:
            with os.scandir(self.path) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                        is_dir = e.is_dir()
                    except OSError:
                        continue
                    entries.append(Entry(e.name, e.path, is_dir, 0 if is_dir else st.st_size, st.st_mtime,
                                         bool(getattr(st, "st_file_attributes", 0) & 0x2)))
        except PermissionError:
            err = "Нет доступа к этой папке"
        except OSError as ex:
            err = ex.strerror or "Не удалось прочитать папку"
        try:
            sort_entries(entries, *self.sort)
        except Exception:
            pass
        self.done.emit(self.token, entries, err)


TAG_COLORS = {"red": ("#ef5350", "Красная"), "orange": ("#ff9f43", "Оранжевая"), "yellow": ("#ffd23f", "Жёлтая"),
              "green": ("#4cd964", "Зелёная"), "blue": ("#4c9aff", "Синяя"), "purple": ("#b07cff", "Фиолетовая")}
_tag_cache = {}


def tagged_icon(base, tag):
    """Значок с цветной точкой-меткой в правом нижнем углу."""
    color = TAG_COLORS.get(tag, ("#ffffff",))[0]
    key = (base.cacheKey(), tag)
    ic = _tag_cache.get(key)
    if ic is None:
        from PySide6.QtGui import QPainter, QColor, QPen
        ic = QIcon()
        for s in (16, 20, 24, 32, 48, 64, 96, 128, 192, 256):
            pm = base.pixmap(s, s)
            if pm.isNull():
                continue
            pm = QPixmap(pm)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            d = max(7, int(min(pm.width(), pm.height()) * 0.36))
            x, y = pm.width() - d - 1, pm.height() - d - 1
            p.setPen(QPen(QColor(255, 255, 255, 235), max(1.2, d / 9)))
            p.setBrush(QColor(color))
            p.drawEllipse(x, y, d, d)
            p.end()
            ic.addPixmap(pm)
        if len(_tag_cache) > 3000:
            _tag_cache.clear()
        _tag_cache[key] = ic
    return ic


class VfsScanWorker(QThread):
    """Содержимое архива (читается в фоне, как и обычная папка)."""
    done = Signal(int, list, str)

    def __init__(self, token, path, sort):
        super().__init__()
        self.token, self.path, self.sort = token, path, sort

    def run(self):
        import vfs
        entries, err = [], ""
        try:
            zpath, inner = vfs.split_zip(self.path)
            idx = vfs.ZipIndex.get(zpath)
            for name, full, is_dir, size, mt in idx.listing(inner):
                entries.append(Entry(name, zpath + "\\" + full, is_dir, size, mt, False, virtual=True))
        except Exception as ex:                       # битый архив, нет доступа и т.п.
            err = f"Не удалось открыть: {ex}"
        try:
            sort_entries(entries, *self.sort)
        except Exception:
            pass
        self.done.emit(self.token, entries, err)


BAD_CHARS = '<>:"/\\|?*'
PER_FILE_ICON = (".exe", ".lnk", ".ico", ".cur", ".scr", ".url", ".appref-ms")


class FsModel(QAbstractTableModel):
    directoryLoaded = Signal(str)
    renamed = Signal(str, str)
    error = Signal(str)
    HEADERS = ("Имя", "Размер", "Тип", "Дата изменения")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = ""
        self._all = []          # все записи папки (в порядке сортировки)
        self._rows = []         # то, что показано (после фильтров)
        self._pos = {}          # путь(в нижнем регистре) -> строка
        self._sort = (0, Qt.AscendingOrder)
        self._show_hidden = False
        self._text = ""
        self._match = None
        self._token = 0
        self._workers = set()
        self.loading = False
        self.show_thumbs = False
        self.tags = {}            # путь (нижний регистр) -> цвет метки; общий словарь из настроек
        self._icons = QFileIconProvider()
        # заглушки (не трогают диск), настоящие значки подгружаются в фоне
        self._folder_icon = self._icons.icon(QFileIconProvider.Folder)
        self._file_icon = self._icons.icon(QFileIconProvider.File)
        self._ext_icons = {}
        self._drive_icon = self._icons.icon(QFileIconProvider.Drive)
        si = shellinfo()
        si.icon_ready.connect(self._shell_icons_changed)
        si.type_ready.connect(self._shell_types_changed)
        self._watch = QFileSystemWatcher(self)
        self._watch.directoryChanged.connect(lambda _p: self._rescan.start())
        self._rescan = QTimer(self)
        self._rescan.setSingleShot(True)
        self._rescan.setInterval(300)
        self._rescan.timeout.connect(lambda: self._start_load(silent=True))
        thumbs().ready.connect(self._thumb_ready)

    # ---------- загрузка ----------
    def rootPath(self):
        return self._root

    def setRootPath(self, path):
        self._root = path or ""
        old = self._watch.directories()
        if old:
            self._watch.removePaths(old)
        self._start_load(silent=False)
        import vfs
        if self._root and not vfs.is_virtual(self._root):
            self._watch.addPath(self._root)

    def reload(self):
        self._start_load(silent=True)

    def shutdown(self):
        """Дождаться фоновых потоков чтения папки (при закрытии окна)."""
        self._token += 1
        for w in list(self._workers):
            w.wait(5000)

    def _start_load(self, silent):
        self._token += 1
        if not self._root:                    # «Этот компьютер» — список дисков
            self._set_all(self._drive_entries(), reset=True)
            self.loading = False
            self.directoryLoaded.emit("")
            return
        if not silent:
            self.beginResetModel()
            self._all, self._rows, self._pos = [], [], {}
            self.endResetModel()
            self.loading = True
        import vfs
        virtual = vfs.is_virtual(self._root)
        w = (VfsScanWorker if virtual else ScanWorker)(self._token, self._root, self._sort)
        self._workers.add(w)
        w.done.connect(self._scanned)
        # сначала дождаться полной остановки потока, потом отпустить (иначе редкий вылет Qt 0xc0000409)
        w.finished.connect(lambda w=w: (w.wait(), self._workers.discard(w)))
        w.start()

    def _drive_entries(self):
        out = []
        for v in QStorageInfo.mountedVolumes():
            if not v.isValid() or not v.isReady():
                continue
            root = v.rootPath().replace("/", "\\")
            drive = root.rstrip("\\")
            label = f"{v.name() or 'Локальный диск'} ({drive})"
            out.append(Entry(root, root, True, v.bytesTotal(), 0, False, label=label, drive=True))
        out.sort(key=lambda e: e.name)
        return out

    def _scanned(self, token, entries, err):
        if token != self._token:
            return
        if err:
            self.error.emit(err)
        was_loading = self.loading
        self.loading = False
        if was_loading:
            self._set_all(entries, reset=True)
        else:
            self._set_all(entries, reset=False)
        self.directoryLoaded.emit(self._root)

    # ---------- фильтры ----------
    def _passes(self, e):
        return (self._show_hidden or not e.hidden) and (self._match is None or self._match(e.name))

    def set_filter(self, show_hidden, text=""):
        from searchpanel import make_matcher
        text = (text or "").strip()
        if show_hidden == self._show_hidden and text == self._text:
            return
        self._show_hidden = show_hidden
        self._text = text
        self._match = make_matcher(text) if text else None
        self.beginResetModel()
        self._rows = [e for e in self._all if self._passes(e)]
        self._reindex()
        self.endResetModel()

    def _reindex(self):
        self._pos = {e.path.lower(): i for i, e in enumerate(self._rows)}

    def _set_all(self, entries, reset):
        if reset:
            self.beginResetModel()
            self._all = entries
            self._rows = [e for e in entries if self._passes(e)]
            self._reindex()
            self.endResetModel()
            return
        # тихое обновление: сохраняем выделение (постоянные индексы переносим по пути файла)
        new_rows = [e for e in entries if self._passes(e)]
        new_pos = {e.path.lower(): i for i, e in enumerate(new_rows)}
        if [e.path for e in new_rows] == [e.path for e in self._rows] and \
                all(a.size == b.size and a.mtime == b.mtime for a, b in zip(new_rows, self._rows)):
            self._all = entries
            return
        self.layoutAboutToBeChanged.emit()
        old_idx = self.persistentIndexList()
        old_paths = [self._rows[i.row()].path.lower() if 0 <= i.row() < len(self._rows) else None for i in old_idx]
        self._all, self._rows, self._pos = entries, new_rows, new_pos
        new_idx = [self.createIndex(new_pos[p], i.column()) if p in new_pos else QModelIndex()
                   for i, p in zip(old_idx, old_paths)]
        self.changePersistentIndexList(old_idx, new_idx)
        self.layoutChanged.emit()

    def sort(self, column, order=Qt.AscendingOrder):
        self._sort = (column, order)
        if not self._all:
            return
        entries = list(self._all)
        sort_entries(entries, column, order)
        self._set_all(entries, reset=False)

    # ---------- доступ к данным ----------
    def entry(self, index):
        r = index.row()
        return self._rows[r] if index.isValid() and 0 <= r < len(self._rows) else None

    def filePath(self, index):
        e = self.entry(index)
        return e.path if e else self._root

    def isDir(self, index):
        e = self.entry(index)
        return bool(e and e.is_dir)

    def size(self, index):
        e = self.entry(index)
        return e.size if e and not e.is_dir else 0

    def lastModified(self, index):
        e = self.entry(index)
        return QDateTime.fromSecsSinceEpoch(int(e.mtime)) if e and e.mtime else QDateTime()

    def index_of(self, path):
        row = self._pos.get(os.path.normpath(path).lower()) if path else None
        return self.createIndex(row, 0) if row is not None else QModelIndex()

    def index(self, row, column=0, parent=QModelIndex()):
        if isinstance(row, str):               # model.index("C:\\папка\\файл")
            return self.index_of(row)
        if parent.isValid() or row < 0 or row >= len(self._rows) or column < 0 or column >= 4:
            return QModelIndex()
        return self.createIndex(row, column)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < 4:
            return self.HEADERS[section]
        return None

    # ---------- значки и тексты ----------
    def _icon(self, e):
        if e.drive:
            if e.virtual:
                return self._drive_icon
            return shellinfo().icon("drive:" + e.path, e.path) or self._drive_icon
        if e.is_dir:
            return self._folder_icon
        by_type = self._ext_icon(e.ext)           # мгновенно, файл не читается
        if e.ext in PER_FILE_ICON and not e.virtual:   # у программ и ярлыков значок свой — подгружаем в фоне
            return shellinfo().icon(e.path, e.path) or by_type
        return by_type

    def _ext_icon(self, ext):
        ic = self._ext_icons.get(ext)
        if ic is None:
            if ext:
                ic = self._icons.icon(QFileInfo("C:/__orca__/x" + ext))   # несуществующий файл: значок берётся по типу
            else:
                ic = self._file_icon
            self._ext_icons[ext] = ic
        return ic

    def _type(self, e):
        if e.drive:
            return "Диск"
        if e.is_dir:
            return "Папка с файлами"
        if e.virtual:
            return f"Файл {e.ext.lstrip('.').upper()}" if e.ext else "Файл"
        t = shellinfo().type(e.ext, e.path)
        if not t or "/" in t:
            t = f"Файл {e.ext.lstrip('.').upper()}" if e.ext else "Файл"
        return t

    def _shell_icons_changed(self):
        n = len(self._rows)
        if n:
            self.dataChanged.emit(self.createIndex(0, 0), self.createIndex(n - 1, 0), [Qt.DecorationRole])

    def refresh_icons(self):
        self._shell_icons_changed()

    def _shell_types_changed(self):
        n = len(self._rows)
        if n:
            self.dataChanged.emit(self.createIndex(0, 2), self.createIndex(n - 1, 2), [Qt.DisplayRole])

    def data(self, index, role=Qt.DisplayRole):
        e = self.entry(index)
        if e is None:
            return None
        c = index.column()
        if role == Qt.DisplayRole:
            if c == 0:
                return e.label or e.name
            if c == 1:
                return fmt_size(e.size) if (e.drive or not e.is_dir) else ""
            if c == 2:
                return self._type(e)
            if c == 3:
                return time.strftime("%d.%m.%Y  %H:%M", time.localtime(e.mtime)) if e.mtime else ""
        elif role == Qt.EditRole and c == 0:
            return e.name
        elif role == Qt.DecorationRole and c == 0:
            ic = None
            if self.show_thumbs and not e.is_dir and not e.virtual and e.ext and (e.ext in IMG_EXT or e.ext in SHELL_EXT):
                ic = thumbs().get(os.path.normpath(e.path))
            if ic is None:
                ic = self._icon(e)
            tag = self.tags.get(e.path.lower()) if self.tags else None
            return tagged_icon(ic, tag) if tag else ic
        elif role == Qt.TextAlignmentRole and c == 1:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.ToolTipRole and c == 0:
            return e.path
        return None

    def _thumb_ready(self, path):
        row = self._pos.get(os.path.normpath(path).lower())
        if row is not None:
            idx = self.createIndex(row, 0)
            self.dataChanged.emit(idx, idx, [Qt.DecorationRole])

    # ---------- перетаскивание ----------
    # готовые наборы флагов: считать их на каждый вызов слишком медленно (Ctrl+A спрашивает флаги у каждой ячейки)
    _F_BASE = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
    _F_EDIT = _F_BASE | Qt.ItemIsEditable
    _F_DIR = _F_BASE | Qt.ItemIsDropEnabled
    _F_DIR_EDIT = _F_BASE | Qt.ItemIsDropEnabled | Qt.ItemIsEditable

    def flags(self, index):
        r = index.row()
        rows = self._rows
        if r < 0 or r >= len(rows) or not index.isValid():
            return Qt.ItemIsDropEnabled
        e = rows[r]
        if e.virtual and not e.drive:
            return self._F_BASE                     # внутри архива ничего менять и класть нельзя, только брать
        editable = index.column() == 0 and not e.drive
        if e.is_dir:
            return self._F_DIR_EDIT if editable else self._F_DIR
        return self._F_EDIT if editable else self._F_BASE

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        md = QMimeData()
        urls, seen, virt = [], set(), []
        for i in indexes:
            e = self.entry(i)
            if e is not None and not e.drive and e.path not in seen:
                seen.add(e.path)
                if e.virtual:
                    virt.append(e.path)
                else:
                    urls.append(QUrl.fromLocalFile(e.path))
        if virt:                                      # из архива: сначала достаём файлы во временную папку
            import vfs
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                real, err = vfs.materialize(virt)
            finally:
                QGuiApplication.restoreOverrideCursor()
            if err:
                self.error.emit(f"Не удалось получить файлы: {err}")
            urls += [QUrl.fromLocalFile(p) for p in real]
        md.setUrls(urls)
        return md

    def supportedDragActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    # ---------- переименование ----------
    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or index.column() != 0:
            return False
        e = self.entry(index)
        if e is None or e.drive:
            return False
        name = str(value).strip()
        old = os.path.normpath(e.path)
        base = os.path.basename(old)
        if not name or name == base:
            return False
        if any(c in BAD_CHARS for c in name) or name.endswith("."):
            self.error.emit('Имя не может содержать \\ / : * ? " < > | и заканчиваться точкой')
            return False
        new = os.path.join(os.path.dirname(old), name)
        if e.virtual:
            self.error.emit("Внутри архива переименовать нельзя")
            return False
        if os.path.exists(new) and name.lower() != base.lower():
            self.error.emit("Файл или папка с таким именем уже есть")
            return False
        try:
            os.rename(old, new)
        except OSError:
            self.error.emit("Не удалось переименовать (возможно, файл занят другой программой)")
            return False
        # обновляем запись и переставляем её на новое место, выделение сохраняется
        e.name, e.path, e.nkey = name, new, nat_key(name)
        e.ext = "" if e.is_dir else os.path.splitext(name)[1].lower()
        entries = list(self._all)
        sort_entries(entries, *self._sort)
        self.layoutAboutToBeChanged.emit()
        old_idx = self.persistentIndexList()
        row_entries = [self._rows[i.row()] if 0 <= i.row() < len(self._rows) else None for i in old_idx]
        self._all = entries
        self._rows = [x for x in entries if self._passes(x)]
        self._reindex()
        by_id = {id(x): i for i, x in enumerate(self._rows)}
        new_idx = [self.createIndex(by_id[id(x)], i.column()) if x is not None and id(x) in by_id else QModelIndex()
                   for i, x in zip(old_idx, row_entries)]
        self.changePersistentIndexList(old_idx, new_idx)
        self.layoutChanged.emit()
        self.renamed.emit(old, new)
        return True
