"""Поиск Everything: модель с постраничной подгрузкой (на подставном движке) и, если Everything установлена,
настоящий запрос к ней."""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["ORCA_NO_POPUP"] = "1"
work = sys.argv[1]

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
import evresults
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


def wait(cond, timeout=6.0):
    t = time.time()
    while time.time() - t < timeout and not cond():
        pump(30)
    return cond()


# ---- подставной движок: 1 000 000 файлов, считаем, какие страницы запрашивались ----
asked = []
TOTAL = 1_000_000


def fake_fetch(text, offset, count, sort):
    asked.append((offset, count, sort))
    n = min(count, TOTAL - offset)
    return TOTAL, [(f"C:\\Фейк\\папка{(offset + i) // 1000}\\файл{offset + i}.txt", False, 100 + offset + i, 1.7e9)
                   for i in range(n)]


m = evresults.EverythingModel(fetch=fake_fetch)
m.start("файл")
wait(lambda: m.total == TOTAL)
check("всего найдено — миллион, а загружена одна страница", m.total == TOTAL and len(m.pages) == 1 and len(asked) == 1)
check("имя и папка строки берутся из пути", m.data(m.index(10, 0)) == "файл10.txt"
      and m.data(m.index(10, 1)) == "C:\\Фейк\\папка0")
m.data(m.index(500_000, 0))
wait(lambda: 500_000 // evresults.PAGE in m.pages)
check("дальняя страница грузится только при показе", len(m.pages) == 2 and m.data(m.index(500_000, 0)) == "файл500000.txt")
check("пока страницы нет — показывается «…», окно не ждёт", m.data(m.index(900_000, 0)) == "…")
m.sort(2, Qt.DescendingOrder)
wait(lambda: m.pages)
check("сортировка по размеру перезапрашивает с нужным порядком", asked[-1][2] == "size_desc")
paths = m.paths_for_rows([5, 1_000, 123_456])
check("пути для действий (копировать/удалить) достаются даже из незагруженных страниц", len(paths) == 3)

# ---- в окне: Ctrl+Shift+F идёт через Everything ----
w = MainWindow(work)
w.resize(1200, 700)
w.move(-6000, 100)
w.show()
F = w.active_folder()
F.eresults.mdl.fetch = fake_fetch
pump(800)
F.show_search(scope=1)
if not F._use_everything():
    print("SKIP  Everything не установлена — проверки окна пропущены")
else:
    F.search_edit.setText("файл")
    F.start_search()
    wait(lambda: F.eresults.mdl.total == TOTAL)
    check("поиск по всему ПК идёт через Everything", F._ev_mode and F.stack.currentWidget() is F.eresults)
    check("строка состояния называет Everything", "Everything" in F.status_text())
    F.close_search()
    check("Esc закрывает поиск и возвращает список", not F.search_active and not F._ev_mode)

    # настоящая Everything (если отвечает)
    F.eresults.mdl.fetch = evresults.default_fetch
    F.show_search(scope=1)
    F.search_edit.setText("ext:py")
    t0 = time.time()
    F.start_search()
    got = wait(lambda: F.eresults.mdl.total > 0 and 0 in F.eresults.mdl.pages, 25)
    dt = time.time() - t0
    check(f"настоящая Everything нашла файлы за {dt:.1f} с (всего {F.eresults.mdl.total})", got)
    if got:
        sample = [F.eresults.mdl.row_data(i)[0] for i in range(0, 20)]
        check("найденные пути настоящие", sum(os.path.exists(p) for p in sample) >= 15)
        F.eresults.selectAll()
        pump(200)
        check("Ctrl+A в результатах не виснет и не выделяет миллионы", 0 < len(F.selected_paths()) <= 20000)
    F.close_search()
w.close()
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
