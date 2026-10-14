"""Режим «значки»: зайти в папку и вернуться — подписи папок должны остаться."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp()
root, out = sys.argv[1], sys.argv[2]

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow

w = MainWindow(root)
w.resize(1100, 600)
w.move(-6000, 100)
w.show()


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


pump(1200)
F = w.active_folder()
F.set_mode("icons")
pump(800)
w.grab().save(os.path.join(out, "ee_1_before.png"))
sub = os.path.join(root, sys.argv[3]) if len(sys.argv) > 3 else os.path.join(root, "Фото")
F.navigate(sub)
pump(1500)
w.grab().save(os.path.join(out, "ee_2_inside.png"))
F.back()
pump(1500)
w.grab().save(os.path.join(out, "ee_3_back.png"))
F.up() if False else None
F.navigate(sub)
pump(800)
F.up()
pump(1500)
w.grab().save(os.path.join(out, "ee_4_up.png"))
v = F.view()
for r in range(min(4, F.model.rowCount())):
    idx = F.model.index(r, 0)
    print(r, repr(F.model.data(idx, Qt.DisplayRole)), v.visualRect(idx).getRect())
app.quit()
