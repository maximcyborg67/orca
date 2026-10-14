"""Архивы как папки: чтение, распаковка, защита от выхода за пределы папки, запрет записи внутрь."""
import os
import shutil
import sys
import tempfile
import zipfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
base = os.path.join(os.path.dirname(sys.argv[1]), "work_vfs")
os.environ["APPDATA"] = tempfile.mkdtemp()
if os.path.exists(base):
    shutil.rmtree(base)
os.makedirs(base)

zpath = os.path.join(base, "архив.zip")
with zipfile.ZipFile(zpath, "w") as z:
    z.writestr("readme.txt", "Привет из архива")
    z.writestr("папка/вложенная/файл.bin", b"\x00\x01\x02" * 50)
    z.writestr("папка/второй.txt", "второй")
    z.writestr("../evil.txt", "не должен выйти")
    z.writestr("пустая/", "")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
import vfs
from mainwin import MainWindow

ok = True


def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and bool(cond)


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


def wait(cond, timeout=10):
    import time
    t = time.time()
    while time.time() - t < timeout and not cond():
        pump(50)
    return cond()


# ---- кодировка старых архивов ----
legacy = SimpleNamespace(filename="привет.txt".encode("cp866").decode("cp437"), flag_bits=0)
check("старое имя из архива (cp866) читается по-русски", vfs._fix_name(legacy) == "привет.txt")

# ---- определение путей ----
check("путь внутри архива распознаётся", vfs.split_zip(zpath + "\\папка\\второй.txt") == (zpath, "папка\\второй.txt"))
check("обычный файл не считается архивом", vfs.split_zip(os.path.join(base, "x")) is None)
idx = vfs.ZipIndex.get(zpath)
check("zip-slip: файл с «..» проигнорирован", "evil.txt" not in idx.entries and "..\\evil.txt" not in idx.entries)
check("папки внутри архива найдены", idx.is_dir("папка") and idx.is_dir("папка\\вложенная") and idx.is_dir("пустая"))

w = MainWindow(base)
w.resize(1100, 650)
w.move(-6000, 100)
w.show()
w.ops.silent = True
F = w.active_folder()
pump(1000)

# ---- архив в окне ----
F.navigate(zpath)
wait(lambda: F.model.rowCount() > 0)
names = [e.name for e in F.model._rows]
check("архив открывается как папка (папки выше файлов)", names == ["папка", "пустая", "readme.txt"])
F.navigate(zpath + "\\папка")
wait(lambda: F.model.rowCount() == 2)
check("вложенная папка архива", [e.name for e in F.model._rows] == ["вложенная", "второй.txt"])
F.up()
wait(lambda: F.path == os.path.normpath(zpath))
check("«вверх» из вложенной папки архива", F.path == os.path.normpath(zpath))
F.up()
wait(lambda: F.path == os.path.normpath(base))
check("«вверх» из архива — папка с архивом", F.path == os.path.normpath(base))

real, err = vfs.materialize([zpath + "\\readme.txt"])
check("файл из архива достаётся во временную папку", real and open(real[0], encoding="utf-8").read() == "Привет из архива")
dest = os.path.join(base, "распаковано")
vfs.extract(zpath, ["папка"], dest)
check("папка из архива распаковывается целиком", os.path.exists(os.path.join(dest, "папка", "вложенная", "файл.bin")))
check("за пределы целевой папки ничего не вышло", not os.path.exists(os.path.join(base, "evil.txt")))

msgs = []
w.ops.message.connect(msgs.append)
src = os.path.join(base, "заметка с пробелами.txt")
open(src, "w", encoding="utf-8").write("обычный файл")
w.ops.transfer([src], zpath + "\\папка", True)
check("в архив класть нельзя (сообщение, файл не создан)", any("архив" in m for m in msgs))
w.ops.delete([zpath + "\\readme.txt"])
check("из архива удалять нельзя", any("архив" in m.lower() for m in msgs))
check("и сам архив цел", zipfile.is_zipfile(zpath))

print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
w.ops.wait_all()
w.close()
app.quit()
