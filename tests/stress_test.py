"""Нагрузка: файлы много раз переносятся туда-обратно между двумя панелями (как у Ricke при перетаскивании),
папки постоянно перечитываются. Программа не должна вылетать."""
import gc
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
base = os.path.join(os.path.dirname(sys.argv[1]), "work_stress")
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 60
os.environ["APPDATA"] = tempfile.mkdtemp()

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow

if os.path.exists(base):
    shutil.rmtree(base)
A, B = os.path.join(base, "Download"), os.path.join(base, "SharedFolder")
os.makedirs(A)
os.makedirs(B)
for i in range(6):
    with open(os.path.join(A, f"app_{i}.apk"), "wb") as f:
        f.write(os.urandom(200_000))

w = MainWindow(A)
w.resize(1200, 700)
w.move(-6000, 100)
w.show()
w.ops.silent = True
w.a_split.setChecked(True)


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


pump(800)
f1, f2 = w.pane1.current_folder(), w.pane2.current_folder()
f1.navigate(A)
f2.navigate(B)
pump(500)
for r in range(rounds):
    src, dst = (A, B) if r % 2 == 0 else (B, A)
    files = [os.path.join(src, n) for n in os.listdir(src)]
    f1.view().selectAll()
    w.ops.transfer(files, dst, copy=False)
    for _ in range(6):                 # частые перечитывания, как при перетаскивании
        f1.model.reload()
        f2.model.reload()
        gc.collect()
        pump(15)
    w.ops.wait_all()
    pump(40)
print("прошло кругов:", rounds, "файлов в A:", len(os.listdir(A)), "в B:", len(os.listdir(B)))
w.close()
print("ИТОГ: ВСЁ В ПОРЯДКЕ (не вылетело)")
app.quit()
