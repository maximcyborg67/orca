"""Перенос файлов должен быть включён во ВСЕХ видах (баг: setMovement(Static) у списка значков молча выключал drag)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(); os.environ["ORCA_NO_INDEX"] = "1"
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv); app.setStyle("Fusion")
import theme; theme.apply(app, "dark")
from mainwin import MainWindow
w = MainWindow(sys.argv[1]); w.move(-6000, 100); w.show()
def pump(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
pump(800); F = w.active_folder(); ok = True
for mode in ("details", "icons", "compact", "icons", "details"):
    F.set_mode(mode); pump(300); v = F.view()
    good = v.dragEnabled() and v.viewport().acceptDrops()
    print(("PASS " if good else "FAIL "), f"{mode}: перенос включён={v.dragEnabled()}, приём={v.viewport().acceptDrops()}")
    ok = ok and good
print("ИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ"); sys.exit(0 if ok else 1)
