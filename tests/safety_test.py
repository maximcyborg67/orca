"""Безопасность: отмена создания папки не должна трогать папку с файлами; журнал действий пишется."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
src = sys.argv[1]
work = os.path.join(os.path.dirname(src), "work_safety")
appdata = tempfile.mkdtemp(prefix="prov_appdata_")
os.environ["APPDATA"] = appdata

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow

if os.path.exists(work):
    shutil.rmtree(work)
shutil.copytree(src, work)
w = MainWindow(work)
w.move(-6000, 100)
w.show()
w.ops.silent = True
F = w.active_folder()
ok = True


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and bool(cond)


pump(1200)
F.new_folder()
pump(500)
newdir = os.path.join(work, "Новая папка")
check("папка создана", os.path.isdir(newdir))
# кладём в неё файл «мимо» Orca (как будто другая программа или позднее сохранение)
with open(os.path.join(newdir, "ценный файл.txt"), "w", encoding="utf-8") as f:
    f.write("важное")
w.ops.undo()
w.ops.wait_all()
pump(400)
check("отмена создания НЕ удалила папку с файлом", os.path.isdir(newdir) and os.path.exists(os.path.join(newdir, "ценный файл.txt")))

# пустую — убирает
F.new_folder()
pump(500)
newdir2 = os.path.join(work, "Новая папка (2)")
check("вторая папка создана", os.path.isdir(newdir2))
w.ops.undo()
check("пустую новую папку отмена убирает", not os.path.exists(newdir2))

# журнал
w.ops.delete([os.path.join(work, "readme.md")], permanent=True)
w.ops.wait_all()
log = os.path.join(appdata, "Provodnik", "actions.log")
txt = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
check("журнал действий записан", "delete-permanent" in txt and "readme.md" in txt)
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
