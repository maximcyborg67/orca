"""Индекс файлов всех дисков для мгновенного поиска «по всему ПК» и для поиска дубликатов.

Строится в фоне (обход дисков без прав администратора, на обычном ПК 1–3 минуты) и хранится в SQLite:
%APPDATA%\\Provodnik\\index.db. Пока строится новая версия, поиск работает по старой; готовая подменяет её целиком.
Ничего на дисках не меняет, только читает имена, размеры и даты."""
import ctypes
import os
import sqlite3
import time

from PySide6.QtCore import QThread, Signal, QObject

import settings

DB = os.path.join(settings.DIR, "index.db")
STALE_SECONDS = 6 * 3600                 # старше — пересобираем при запуске
SKIP_DIRS = {"$recycle.bin", "system volume information", "winsxs", "$windows.~bt", "$windows.~ws", "windows.old", "$winreagent"}
HIDDEN, REPARSE = 0x2, 0x400
# системные места, которые не предлагаем как «дубликаты» (их копии нужны Windows и программам)
SYSTEM_PREFIXES = ("c:\\windows\\", "c:\\program files\\", "c:\\program files (x86)\\", "c:\\programdata\\")
MAX_RESULTS = 20000
ROOTS = None                              # для тестов: обходить только эти папки вместо всех дисков

SCHEMA = """
PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
CREATE TABLE dirs(id INTEGER PRIMARY KEY, path TEXT NOT NULL);
CREATE TABLE files(name_lc TEXT NOT NULL, name TEXT NOT NULL, dir_id INTEGER NOT NULL, is_dir INTEGER NOT NULL,
                   size INTEGER NOT NULL, mtime REAL NOT NULL, hidden INTEGER NOT NULL);
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
"""


def fixed_drives():
    out = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:         # только жёсткие диски и SSD
                out.append(root)
    return out


def info():
    """(число записей, время сборки) или None, если индекса ещё нет."""
    try:
        db = sqlite3.connect(DB)
        try:
            m = dict(db.execute("SELECT k, v FROM meta"))
        finally:
            db.close()
        return int(m["count"]), float(m["built"])
    except (sqlite3.Error, KeyError, OSError, ValueError):
        return None


class IndexBuilder(QThread):
    progress = Signal(int)
    done = Signal(bool, int)             # прервано?, сколько записей

    def __init__(self):
        super().__init__()
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        self.setPriority(QThread.LowPriority)
        os.makedirs(settings.DIR, exist_ok=True)
        tmp = DB + ".new"
        for p in (tmp,):
            try:
                os.remove(p)
            except OSError:
                pass
        total = 0
        ok = False
        try:
            db = sqlite3.connect(tmp)
            db.executescript(SCHEMA)
            batch, next_id = [], 0
            stack = []
            for root in (ROOTS or fixed_drives()):
                next_id += 1
                db.execute("INSERT INTO dirs VALUES(?,?)", (next_id, root))
                stack.append((root, next_id))
            while stack and not self._cancel:
                cur, cid = stack.pop()
                try:
                    it = os.scandir(cur)
                except OSError:
                    continue
                with it:
                    for e in it:
                        try:
                            name = e.name
                            st = e.stat(follow_symlinks=False)
                            attrs = getattr(st, "st_file_attributes", 0)
                            is_dir = e.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        if is_dir:
                            if name.lower() in SKIP_DIRS or attrs & REPARSE:          # ссылки и «мусорные» папки не обходим
                                continue
                            next_id += 1
                            db.execute("INSERT INTO dirs VALUES(?,?)", (next_id, e.path))
                            stack.append((e.path, next_id))
                        batch.append((name.lower(), name, cid, 1 if is_dir else 0, 0 if is_dir else st.st_size, st.st_mtime, 1 if attrs & HIDDEN else 0))
                        total += 1
                if len(batch) >= 20000:
                    db.executemany("INSERT INTO files VALUES(?,?,?,?,?,?,?)", batch)
                    batch = []
                    self.progress.emit(total)
            if batch:
                db.executemany("INSERT INTO files VALUES(?,?,?,?,?,?,?)", batch)
            if not self._cancel:
                db.execute("CREATE INDEX ix_size ON files(size) WHERE is_dir=0")
                db.execute("CREATE INDEX ix_dir ON files(dir_id)")
                db.execute("INSERT INTO meta VALUES('count', ?)", (str(total),))
                db.execute("INSERT INTO meta VALUES('built', ?)", (str(time.time()),))
            db.commit()
            db.close()
            if not self._cancel:
                for _ in range(20):                    # если в этот момент идёт чтение старой версии, пробуем ещё раз
                    try:
                        os.replace(tmp, DB)
                        ok = True
                        break
                    except OSError:
                        time.sleep(0.5)
        except sqlite3.Error:
            pass
        finally:
            if not ok:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            self.done.emit(not ok, total)


def _parse(text):
    words = [w for w in text.lower().split() if w]
    return [w for w in words if "*" not in w and "?" not in w], [w for w in words if "*" in w or "?" in w]


class IndexSearchWorker(QThread):
    """Тот же интерфейс, что у SearchWorker (found / finished_search), но ищет по индексу и отвечает почти сразу."""
    found = Signal(list)
    finished_search = Signal(bool)

    def __init__(self, text, show_hidden, under=None):
        super().__init__()
        from searchpanel import _ALIVE
        _ALIVE.add(self)
        self.finished.connect(lambda: (self.wait(), _ALIVE.discard(self)))
        self.plain, self.wild = _parse(text)
        self.show_hidden = show_hidden
        self.under = os.path.normpath(under).lower() if under else None
        self._cancel = False
        self.count = 0

    def cancel(self):
        self._cancel = True

    def run(self):
        cancelled = False
        try:
            where, args = [], []
            for w in self.plain:
                where.append("instr(f.name_lc, ?) > 0")
                args.append(w)
            for w in self.wild:
                where.append("f.name_lc GLOB ?")
                args.append(w)
            if not where:
                return
            if not self.show_hidden:
                where.append("f.hidden = 0")
            sql = ("SELECT d.path, f.name, f.is_dir, f.size, f.mtime FROM files f JOIN dirs d ON d.id = f.dir_id WHERE "
                   + " AND ".join(where) + f" LIMIT {MAX_RESULTS}")
            db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
            try:
                cur = db.execute(sql, args)
                while not self._cancel:
                    rows = cur.fetchmany(200)
                    if not rows:
                        break
                    out = []
                    for dpath, name, is_dir, size, mt in rows:
                        path = os.path.join(dpath, name)
                        if self.under and not path.lower().startswith(self.under):
                            continue
                        if os.path.exists(path):                          # индекс мог устареть
                            out.append((path, bool(is_dir), size, mt))
                    if out:
                        self.count += len(out)
                        self.found.emit(out)
                cancelled = self._cancel
            finally:
                db.close()
        except sqlite3.Error:
            cancelled = True
        finally:
            self.finished_search.emit(cancelled)


def candidates_by_size(min_size, include_hidden, include_system=False):
    """Для поиска дубликатов по всему ПК: {размер: [(путь, время), …]} только там, где размер повторяется."""
    out = {}
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        sizes = [r[0] for r in db.execute("SELECT size FROM files WHERE is_dir=0 AND size>=? GROUP BY size HAVING count(*)>1", (min_size,))]
        for i in range(0, len(sizes), 500):
            chunk = sizes[i:i + 500]
            q = ",".join("?" * len(chunk))
            for dpath, name, size, mt, hid in db.execute(
                    f"SELECT d.path, f.name, f.size, f.mtime, f.hidden FROM files f JOIN dirs d ON d.id=f.dir_id "
                    f"WHERE f.is_dir=0 AND f.size IN ({q})", chunk):
                if hid and not include_hidden:
                    continue
                path = os.path.join(dpath, name)
                if not include_system and path.lower().startswith(SYSTEM_PREFIXES):
                    continue
                out.setdefault(size, []).append((path, mt))
    finally:
        db.close()
    return {s: v for s, v in out.items() if len(v) > 1}


class FileIndex(QObject):
    """Хозяин индекса: сам обновляет его в фоне, сообщает состояние для строки статуса."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.builder = None
        self.progress = 0

    @property
    def building(self):
        return self.builder is not None

    def refresh_if_stale(self):
        i = info()
        if i is None or time.time() - i[1] > STALE_SECONDS:
            self.rebuild()

    def rebuild(self):
        if self.builder is not None:
            return
        b = IndexBuilder()
        b.progress.connect(self._progress)
        b.done.connect(self._done)
        self.builder = b
        self.progress = 0
        b.start()
        self.changed.emit()

    def _progress(self, n):
        self.progress = n
        self.changed.emit()

    def _done(self, cancelled, total):
        b, self.builder = self.builder, None
        if b is not None:
            b.wait(5000)          # поток ещё доделывает последние строки — не отпускаем его раньше времени (иначе вылет Qt)
        self.changed.emit()

    def stop(self):
        if self.builder is not None:
            self.builder.cancel()
            self.builder.wait(5000)

    def status_text(self):
        if self.building:
            return f"Индекс: обновляется… {self.progress:,}".replace(",", " ")
        i = info()
        if i is None:
            return "Индекс: нет"
        return f"Индекс: {i[0]:,} файлов".replace(",", " ")
