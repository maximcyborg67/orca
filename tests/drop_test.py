"""Бросание файлов: на пустое место списка, на папку, на вкладку, на часть пути, на боковую панель."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
src = sys.argv[1]
work = os.path.join(os.path.dirname(src), "work_drop")
os.environ["APPDATA"] = tempfile.mkdtemp()

from PySide6.QtCore import QEventLoop, QTimer, Qt, QMimeData, QUrl, QPointF, QPoint
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow

if os.path.exists(work):
    shutil.rmtree(work)
shutil.copytree(src, work)
os.makedirs(os.path.join(work, "Цель"), exist_ok=True)
w = MainWindow(work)
w.resize(1300, 800)
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


def mime(*paths):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return md


def drop(widget, pos, md, mods=Qt.NoModifier):
    ev = QDropEvent(QPointF(pos), Qt.MoveAction, md, Qt.LeftButton, mods)
    widget.dropEvent(ev)
    w.ops.wait_all()


pump(1500)
# 1) на пустое место списка (в другой вкладке/папке)
os.makedirs(os.path.join(work, "Пусто"), exist_ok=True)
F.navigate(os.path.join(work, "Пусто"))
pump(800)
vp = F.view().viewport()
drop(F.view(), QPoint(vp.width() - 20, vp.height() - 20), mime(os.path.join(work, "readme.md")))
check("бросок на пустое место списка кладёт файл в открытую папку",
      os.path.exists(os.path.join(work, "Пусто", "readme.md")) and not os.path.exists(os.path.join(work, "readme.md")))

# 2) на вкладку
F.navigate(work)
pump(500)
w.active_pane().add_tab(os.path.join(work, "Цель"))
pump(500)
bar = w.active_pane().tabBar()
pos = bar.tabRect(1).center()
drop(bar, pos, mime(os.path.join(work, "данные.json")))
check("бросок на вкладку кладёт файл в её папку", os.path.exists(os.path.join(work, "Цель", "данные.json")))

# 3) на часть пути
w.active_pane().setCurrentIndex(1)
pump(300)
F2 = w.active_folder()
btn = None
for g in F2.pathbar.crumbs.groups:
    from pathbar import _CrumbButton
    b = g.findChild(_CrumbButton)
    if b is not None and b.text() == "work_drop":
        btn = b
check("часть пути найдена", btn is not None)
if btn is not None:
    md3 = mime(os.path.join(work, "Цель", "данные.json"))   # держим ссылку, иначе Qt получит «пустой» объект
    ev = QDropEvent(QPointF(5, 5), Qt.MoveAction, md3, Qt.LeftButton, Qt.NoModifier)
    btn.dropEvent(ev)
    w.ops.wait_all()
    check("бросок на часть пути (родительская папка) переносит файл туда",
          os.path.exists(os.path.join(work, "данные.json")) and not os.path.exists(os.path.join(work, "Цель", "данные.json")))
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
