"""Режим «значки»: ячейки не сжимаются, если первое имя очень длинное и без пробелов (раньше пропадали подписи)."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp()
base = os.path.join(os.path.dirname(sys.argv[1]), "work_cells")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow

if os.path.exists(base):
    shutil.rmtree(base)
os.makedirs(os.path.join(base, "A" * 40))
os.makedirs(os.path.join(base, "Короткая"))
os.makedirs(os.path.join(base, "BlueStacks-Tiramisu64"))
open(os.path.join(base, "файл.txt"), "w").write("x")
w = MainWindow(base)
w.resize(1100, 600)
w.move(-6000, 100)
w.show()


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


pump(1200)
F = w.active_folder()
ok = True
for size in (96, 64, 160):
    F.set_mode("icons")
    F.set_icon_size(size)
    pump(700)
    v = F.view()
    heights = {F.model.index(r, 0) and v.visualRect(F.model.index(r, 0)).height() for r in range(F.model.rowCount())}
    good = len(heights) == 1 and min(heights) >= size + 20
    print(("PASS " if good else "FAIL "), f"значки {size}: высоты ячеек {sorted(heights)}")
    ok = ok and good
F.set_mode("compact")
pump(500)
v = F.view()
hs = {v.visualRect(F.model.index(r, 0)).height() for r in range(F.model.rowCount())}
print(("PASS " if len(hs) == 1 else "FAIL "), "компактно: высоты", sorted(hs))
ok = ok and len(hs) == 1
print("ИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
