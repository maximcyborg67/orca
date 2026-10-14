"""Настоящее событие «правая кнопка» должно вызывать меню (на файле, на пустом месте, в значках и в результатах поиска)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp()
work = sys.argv[1]

from PySide6.QtCore import QEventLoop, QTimer, QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import theme
theme.apply(app, "dark")
from mainwin import MainWindow
import folderview

w = MainWindow(work)
w.move(-6000, 100)
w.show()
F = w.active_folder()


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


calls = []
F.show_context = lambda gpos, on_item: calls.append(on_item)   # вместо настоящего меню (оно модальное)
ok = True


def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and cond


pump(1500)


def rclick(view, pos):
    ev = QContextMenuEvent(QContextMenuEvent.Mouse, pos, view.viewport().mapToGlobal(pos))
    QApplication.sendEvent(view.viewport(), ev)


for mode in ("details", "icons", "compact"):
    F.set_mode(mode)
    pump(700)
    v = F.view()
    idx = F.model.index(0, 0, v.rootIndex())
    pos = v.visualRect(idx).center()
    calls.clear()
    rclick(v, pos)
    check(f"{mode}: правая кнопка на файле/папке вызывает меню", calls == [True])
    calls.clear()
    rclick(v, QPoint(v.viewport().width() - 5, v.viewport().height() - 5))
    check(f"{mode}: правая кнопка на пустом месте вызывает меню", calls == [False])

F.set_mode("details")
F.show_search()
F.search_edit.setText("картинка")
F.start_search()
for _ in range(100):
    pump(50)
    if not F._searching:
        break
v = F.results
calls.clear()
it = v.topLevelItem(0)
rclick(v, v.visualItemRect(it).center())
check("результаты поиска: правая кнопка вызывает меню", calls == [True])
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
