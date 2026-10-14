"""Мелкие общие функции."""
import os


def fmt_size(n):
    """Размер файла по-русски: 1,5 МБ."""
    if n is None or n < 0:
        return ""
    if n < 1024:
        return f"{n} Б"
    v = float(n)
    for unit in ("КБ", "МБ", "ГБ", "ТБ", "ПБ"):
        v /= 1024.0
        if v < 1024 or unit == "ПБ":
            s = f"{v:.0f}" if v >= 100 else f"{v:.1f}"
            return f"{s.replace('.', ',')} {unit}"
    return f"{n} Б"


def plural(n, one, few, many):
    """1 файл, 2 файла, 5 файлов."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def norm_path(path):
    """Единый вид пути: обратные слэши, у диска — со слэшем в конце. Пустая строка = «Этот компьютер»."""
    if not path:
        return ""
    p = os.path.normpath(path)
    if len(p) == 2 and p[1] == ":":
        p += "\\"
    return p


def drive_of(path):
    return os.path.splitdrive(path)[0].upper()


def folder_size(paths):
    """(общий размер, число файлов, число папок) для списка файлов и папок. Ссылки-«переходы» не раскрываются."""
    total = files = dirs = 0
    stack = []
    for p in paths:
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                stack.append(p)             # сама выбранная папка в «число папок» не входит — считаем только вложенные
            else:
                total += os.path.getsize(p)
                files += 1
        except OSError:
            pass
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        dirs += 1
                        stack.append(e.path)
                    else:
                        total += e.stat(follow_symlinks=False).st_size
                        files += 1
                except OSError:
                    continue
    return total, files, dirs


def unique_name(folder, base, ext=""):
    """Новая папка, Новая папка (2)…"""
    name = base + ext
    n = 2
    while os.path.exists(os.path.join(folder, name)):
        name = f"{base} ({n}){ext}"
        n += 1
    return name
