"""Названия в строке пути не должны налезать друг на друга ни при какой ширине."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp()
deep = sys.argv[1]

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow

w = MainWindow(deep)
w.move(-6000, 100)
w.show()


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


ok = True
for width in (1560, 1100, 800, 1300):
    w.resize(width, 700)
    pump(500)
    F = w.active_folder()
    vis = [g for g in F.pathbar.crumbs.groups if g.isVisible()]
    vis.sort(key=lambda g: g.x())
    overlap = any(a.x() + a.width() > b.x() + 1 for a, b in zip(vis, vis[1:]))
    inside = all(g.x() + g.width() <= F.pathbar.crumbs.width() + 1 for g in vis)
    last_visible = bool(vis) and vis[-1] is F.pathbar.crumbs.groups[-1]
    # «призраки»: видимые дети, которых нет в списке частей (старые, ещё не удалённые)
    from PySide6.QtWidgets import QWidget
    ghosts = [c for c in F.pathbar.crumbs.children() if isinstance(c, QWidget) and c.isVisible()
              and c not in F.pathbar.crumbs.groups]
    if ghosts:
        overlap = True
    # много переходов подряд — призраков остаться не должно
    for _ in range(6):
        F.navigate(os.path.dirname(F.path) if F.path else deep)
        F.navigate(deep)
    pump(300)
    ghosts2 = [c for c in F.pathbar.crumbs.children() if isinstance(c, QWidget) and c.isVisible()
               and c not in F.pathbar.crumbs.groups]
    if ghosts2:
        overlap = True
    print(("PASS " if not overlap and inside and last_visible else "FAIL "), f"ширина {width}: видно {len(vis)} из {len(F.pathbar.crumbs.groups)}",
          "налезают" if overlap else "", "" if inside else "выходят за рамку", "" if last_visible else "последняя папка скрыта")
    ok = ok and not overlap and inside and last_visible
print("ИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
