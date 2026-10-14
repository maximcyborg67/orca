"""Проверка родного меню Windows: собирается ли оно, какие пункты, рисуется ли на экране, закрывается ли по Esc."""
import ctypes
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp()
f = sys.argv[1]
out = sys.argv[2]

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import theme
theme.apply(app, "dark")
from mainwin import MainWindow
import nativemenu as nm

w = MainWindow(os.path.dirname(f))
w.move(-6000, 100)
w.show()
app.processEvents()
hwnd = int(w.winId())

# 1) состав меню без показа
ctx = nm._Ctx([f], hwnd)
hmenu = nm.user32.CreatePopupMenu()
hr = ctx.query(hmenu, nm.CMF_NORMAL | nm.CMF_EXPLORE | nm.CMF_CANRENAME | nm.CMF_ITEMMENU)
items = nm.menu_items(hmenu)
print("QueryContextMenu hr =", hr, " пунктов:", len(items))
print([i for i in items if i])
print("IContextMenu3:", ctx.pcm3 is not None, " IContextMenu2:", ctx.pcm2 is not None)
nm.user32.DestroyMenu(hmenu)
ctx.close()

# 2) настоящий показ: через 1.2 с снимок экрана, через 2 с — Esc
def later():
    from PIL import ImageGrab
    time.sleep(1.2)
    ImageGrab.grab().save(out)
    time.sleep(0.4)
    ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)

ctypes.windll.user32.SetCursorPos(500, 300)
threading.Thread(target=later, daemon=True).start()
called = []
res = nm.popup([f], hwnd, [("Открыть в новой вкладке", lambda: called.append(1))], {}, False)
print("popup вернул:", res, "; выбран наш пункт:", bool(called))
app.quit()
