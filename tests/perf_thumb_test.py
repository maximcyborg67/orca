"""1) Большая папка (много файлов): сколько окно «подвисает» при открытии и выделении всего.
2) Миниатюра видео от Windows появляется в режиме «значки»."""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp()
big, vid_dir = sys.argv[1], sys.argv[2]

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow
import fsmodel

w = MainWindow(vid_dir)
w.resize(1300, 800)
w.move(-6000, 100)
w.show()
F = w.active_folder()

last = [time.perf_counter()]
gaps = []
hb = QTimer()
hb.setInterval(15)


def beat():
    now = time.perf_counter()
    gaps.append(now - last[0])
    last[0] = now


hb.timeout.connect(beat)
hb.start()


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


ok = True


def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name, extra)
    ok = ok and bool(cond)


# --- миниатюра видео ---
pump(1200)
F.set_mode("icons")
vid = os.path.join(vid_dir, "тест видео.mp4")
t0 = time.time()
ic = None
while time.time() - t0 < 12:
    pump(200)
    w.grab()      # окно за пределами экрана само не перерисовывается, а миниатюры запрашиваются при отрисовке
    ic = fsmodel.thumbs().cache.get(os.path.normpath(vid))
    if ic is not None:
        break
check("миниатюра видео получена от Windows", ic not in (None, False), f"({round(time.time() - t0, 1)} с)")

# --- большая папка ---
for mode in ("details", "icons"):
    F.set_mode(mode)
    pump(300)
    gaps.clear()
    t0 = time.perf_counter()
    F.navigate(big)
    deadline = time.time() + 40
    while time.time() < deadline:
        pump(100)
        if F.model.rowCount(F.tree.rootIndex()) >= 30000:
            break
    load = time.perf_counter() - t0
    n = F.model.rowCount(F.tree.rootIndex())
    mx = max(gaps) if gaps else 0
    check(f"{mode}: открытие папки ({n} файлов) за {load:.1f} с, самое долгое подвисание {mx * 1000:.0f} мс", n >= 30000 and mx < 1.5)
    gaps.clear()
    t1 = time.perf_counter()
    F.view().selectAll()
    pump(600)
    txt = F.status_text()
    mx2 = max(gaps) if gaps else 0
    check(f"{mode}: выделить всё — подвисание {mx2 * 1000:.0f} мс", mx2 < 2.5, "| " + txt)
    F.view().clearSelection()
    pump(200)
print("ИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
