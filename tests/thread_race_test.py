"""Опыт: «гонка» при удалении фонового потока по сигналу finished.
Режим old — как было в Orca (ссылку бросаем сразу), new — сначала wait()."""
import gc
import sys

from PySide6.QtCore import QCoreApplication, QThread, QTimer

mode = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
app = QCoreApplication(sys.argv)
alive = set()
done = [0]


class W(QThread):
    def run(self):
        pass


def start_one():
    w = W()
    alive.add(w)

    def fin(w=w):
        if mode == "new":
            w.wait()
        alive.discard(w)
        gc.collect(0)
        done[0] += 1
        if done[0] >= N:
            print("готово без вылета:", done[0])
            app.quit()
        else:
            start_one()
    w.finished.connect(fin)
    w.start()


for _ in range(8):
    start_one()
QTimer.singleShot(120000, app.quit)
app.exec()
