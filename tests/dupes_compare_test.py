"""Поиск дубликатов и сравнение папок: логика и безопасность."""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
base = os.path.join(os.path.dirname(sys.argv[1]), "work_dc")
os.environ["APPDATA"] = tempfile.mkdtemp()

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")

if os.path.exists(base):
    shutil.rmtree(base)
A, B = os.path.join(base, "A"), os.path.join(base, "B")
for d in (A, os.path.join(A, "sub"), B, os.path.join(B, "sub")):
    os.makedirs(d)


def w(path, data):
    with open(path, "wb") as f:
        f.write(data)


big = os.urandom(300_000)
w(os.path.join(A, "один.bin"), big)
w(os.path.join(A, "sub", "копия один.bin"), big)                 # дубликат по содержимому
w(os.path.join(B, "ещё копия.bin"), big)
w(os.path.join(A, "почти.bin"), big[:-1] + b"X")                 # тот же размер, другое содержимое
w(os.path.join(A, "маленький.txt"), b"abc")                      # меньше порога
w(os.path.join(A, "маленький2.txt"), b"abc")
w(os.path.join(A, "общий.txt"), b"same")
w(os.path.join(B, "общий.txt"), b"same")
shutil.copystat(os.path.join(A, "общий.txt"), os.path.join(B, "общий.txt"))
w(os.path.join(A, "только_слева.txt"), b"L")
w(os.path.join(B, "только_справа.txt"), b"R")
w(os.path.join(A, "sub", "разный.txt"), b"old version")
w(os.path.join(B, "sub", "разный.txt"), b"new version, longer")
os.utime(os.path.join(B, "sub", "разный.txt"), (time.time() + 100, time.time() + 100))

ok = True


def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and bool(cond)


from dupes import DupWorker
groups = []
wk = DupWorker([base], 1024, False)
wk.found.connect(groups.append)
wk.run()
check("нашлась одна группа дубликатов", len(groups) == 1)
names = sorted(os.path.basename(p) for p, _s, _m in groups[0]) if groups else []
check("в группе 3 копии (по содержимому, имена разные)", names == ["ещё копия.bin", "копия один.bin", "один.bin"])
check("файл с тем же размером, но другим содержимым не попал в группу", "почти.bin" not in names)
check("файлы меньше порога не учитываются", all("маленький" not in n for n in names))

from compare import compare_trees
only_l, only_r, diff, same = compare_trees(A, B)
check("только слева: файлы без пары", {x[0] for x in only_l} >= {"только_слева.txt", "один.bin"})
check("только справа найдено", "только_справа.txt" in {x[0] for x in only_r})
check("отличающийся файл найден", any(d[0][0].endswith("разный.txt") for d in diff))
check("одинаковый файл посчитан как одинаковый", same >= 1 and not any(d[0][0] == "общий.txt" for d in diff))

# диалог дубликатов: защита «нельзя отметить все копии»
from mainwin import MainWindow
mw = MainWindow(base)
mw.move(-6000, 100)
mw.show()
mw.ops.silent = True
from dupes import DuplicatesDialog
dlg = DuplicatesDialog(mw, [base])
dlg.chk_hidden.setChecked(False)
dlg.min_kb.setValue(1)
dlg.start()
for _ in range(100):
    l = QEventLoop(); QTimer.singleShot(100, l.quit); l.exec()
    if dlg.worker is not None and dlg.worker.isFinished():
        break
l = QEventLoop(); QTimer.singleShot(300, l.quit); l.exec()
check("диалог показал группу", dlg.tree.topLevelItemCount() == 1)
dlg._auto_mark(oldest=True)
marked = [os.path.basename(it.data(0, Qt.UserRole)) for it in dlg._checked()]
check("автоотметка: отмечено 2 из 3 (старейший остаётся)", len(marked) == 2)
mw.ops.delete([it.data(0, Qt.UserRole) for it in dlg._checked()], permanent=True, confirm=False)
mw.ops.wait_all()
left = [p for p in (os.path.join(A, "один.bin"), os.path.join(A, "sub", "копия один.bin"), os.path.join(B, "ещё копия.bin"))
        if os.path.exists(p)]
check("после удаления лишних остаётся ровно один файл", len(left) == 1)
dlg.close()
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
