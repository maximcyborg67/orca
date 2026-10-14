"""Ctrl+цифры переключают вкладки (как в браузере), Ctrl+Shift+цифры — вид."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
work = sys.argv[1]
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["ORCA_NO_POPUP"] = "1"

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
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


w = MainWindow(work)
w.resize(1100, 650)
w.move(-6000, 100)
w.show()
pump(800)
pane = w.active_pane()
for sub in ("Фото", "Документы", "Музыка", "Проекты"):
    pane.add_tab(os.path.join(work, sub))
pump(300)
check("открыто 5 вкладок", pane.count() == 5)
keys = {a.shortcut().toString(): a for a in w.actions() if a.shortcut().toString()}
for n in range(1, 10):
    check(f"горячая клавиша Ctrl+{n} есть", f"Ctrl+{n}" in keys)
keys["Ctrl+2"].trigger()
check("Ctrl+2 — вторая вкладка", pane.currentIndex() == 1)
keys["Ctrl+5"].trigger()
check("Ctrl+5 — пятая вкладка", pane.currentIndex() == 4)
keys["Ctrl+9"].trigger()
check("Ctrl+9 — последняя вкладка", pane.currentIndex() == 4)
keys["Ctrl+1"].trigger()
check("Ctrl+1 — первая вкладка", pane.currentIndex() == 0)
keys["Ctrl+8"].trigger()
check("несуществующий номер вкладки ничего не ломает", pane.currentIndex() == 0)
for i, mode in enumerate(("icons", "compact", "details")):
    a = keys.get(f"Ctrl+Shift+{i + 1}")
    check(f"Ctrl+Shift+{i + 1} — вид «{mode}»", a is not None and a is w.act_mode[mode])
a = keys["Ctrl+Shift+1"]
a.trigger()
pump(200)
check("Ctrl+Shift+1 включает значки", w.active_folder().mode == "icons")
w.close()
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
