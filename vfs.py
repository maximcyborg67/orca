"""Виртуальные папки: содержимое архивов (zip, apk, jar…).
Путь внутри архива:  C:\\папка\\файл.zip\\внутри\\файл.txt
Ничего не записывается внутрь архивов."""
import hashlib
import os
import shutil
import tempfile
import zipfile

CONTAINER_EXT = (".zip", ".apk", ".jar", ".xapk", ".apks", ".aar")
OPEN_ON_ENTER = (".zip",)            # Enter по такому файлу открывает его как папку
TEMP_ROOT = os.path.join(tempfile.gettempdir(), "Orca")


# ======================= определение типа пути =======================
def split_zip(path):
    """(путь_к_архиву, внутренний_путь) или None."""
    if not path or "\\" not in path:
        return None
    low = path.lower()
    if not any(ext in low for ext in CONTAINER_EXT):
        return None
    parts = path.split("\\")
    acc = parts[0] + "\\"
    for i, part in enumerate(parts[1:], 1):
        acc = os.path.join(acc, part)
        if part.lower().endswith(CONTAINER_EXT) and os.path.isfile(acc):
            return acc, "\\".join(parts[i + 1:])
    return None


def is_zip_path(path):
    return split_zip(path) is not None


def is_virtual(path):
    return is_zip_path(path)


def isdir(path):
    """Папка ли это (настоящая или виртуальная)."""
    if not path:
        return True
    z = split_zip(path)
    if z:
        try:
            return ZipIndex.get(z[0]).is_dir(z[1])
        except (OSError, zipfile.BadZipFile):
            return False
    return os.path.isdir(path)


# ======================= архивы =======================
def _fix_name(zi):
    n = zi.filename
    if zi.flag_bits & 0x800:
        return n
    try:
        alt = n.encode("cp437").decode("cp866")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return n
    cyr = lambda s: any("\u0400" <= ch <= "\u04ff" for ch in s)
    return alt if cyr(alt) and not cyr(n) else n


class ZipIndex:
    _cache = {}

    @classmethod
    def get(cls, zpath):
        m = os.path.getmtime(zpath)
        c = cls._cache.get(zpath)
        if c is None or c.mtime != m:
            c = cls(zpath, m)
            if len(cls._cache) > 12:
                cls._cache.clear()
            cls._cache[zpath] = c
        return c

    def __init__(self, zpath, mtime):
        self.zpath, self.mtime = zpath, mtime
        self.entries = {}      # внутренний путь (через \\) -> (is_dir, size, mtime, ZipInfo|None)
        self.children = {"": {}}
        import time
        with zipfile.ZipFile(zpath) as zf:
            for zi in zf.infolist():
                name = _fix_name(zi).replace("\\", "/")
                is_dir = name.endswith("/")
                parts = [p for p in name.split("/") if p and p != "."]
                if not parts or any(p == ".." for p in parts) or ":" in parts[0]:
                    continue                      # защита от «zip-slip»
                try:
                    mt = time.mktime(zi.date_time + (0, 0, -1))
                except (ValueError, OverflowError):
                    mt = 0
                acc = ""
                for i, p in enumerate(parts):
                    parent = acc
                    acc = p if not acc else acc + "\\" + p
                    last = i == len(parts) - 1
                    d = (not last) or is_dir
                    if acc not in self.entries or (last and not d):
                        self.entries[acc] = (d, 0 if d else zi.file_size, mt, zi if last and not d else None)
                    self.children.setdefault(parent, {})[p] = acc
                    if d:
                        self.children.setdefault(acc, {})

    def is_dir(self, inner):
        inner = inner.strip("\\")
        return inner == "" or (inner in self.entries and self.entries[inner][0])

    def listing(self, inner):
        inner = inner.strip("\\")
        out = []
        for name, full in sorted(self.children.get(inner, {}).items(), key=lambda kv: kv[0].lower()):
            d, size, mt, _zi = self.entries[full]
            out.append((name, full, d, size, mt))
        return out


def extract(zpath, inner_paths, dest_dir):
    """Распаковать выбранное (файлы и папки) в dest_dir. Возвращает список созданных верхних путей."""
    idx = ZipIndex.get(zpath)
    os.makedirs(dest_dir, exist_ok=True)
    made = []
    with zipfile.ZipFile(zpath) as zf:
        for inner in inner_paths:
            inner = inner.strip("\\")
            base = os.path.basename(inner) or os.path.splitext(os.path.basename(zpath))[0]
            top = os.path.join(dest_dir, base)
            made.append(top)
            targets = [(k, v) for k, v in idx.entries.items() if k == inner or k.startswith(inner + "\\")] \
                if inner else list(idx.entries.items())
            if inner and inner in idx.entries and idx.entries[inner][0] is False:
                targets = [(inner, idx.entries[inner])]
            os.makedirs(top, exist_ok=True) if (not inner or idx.is_dir(inner)) else None
            for key, (is_dir, size, mt, zi) in targets:
                rel = key[len(inner):].strip("\\") if inner else key
                out = os.path.join(top, rel) if rel else top
                if is_dir:
                    os.makedirs(out, exist_ok=True)
                elif zi is not None:
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with zf.open(zi) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
    return made


def temp_dir_for(zpath):
    h = hashlib.sha1((zpath + str(os.path.getmtime(zpath))).encode("utf-8", "ignore")).hexdigest()[:10]
    d = os.path.join(TEMP_ROOT, "zip", h)
    os.makedirs(d, exist_ok=True)
    return d


# ======================= общие операции =======================
def materialize(paths, progress=None):
    """Скачать/распаковать виртуальные пути во временную папку. Возвращает (реальные_пути, ошибка)."""
    real, err = [], ""
    for p in paths:
        if not is_virtual(p):
            real.append(p)
            continue
        zpath, inner = split_zip(p)
        if progress:
            progress(f"Распаковываю: {os.path.basename(p)}")
        try:
            real.extend(extract(zpath, [inner], temp_dir_for(zpath)))
        except (OSError, zipfile.BadZipFile) as e:
            err = str(e)
    return real, err
