"""Своя модель: слежение за папкой, сортировка, «Этот компьютер», выделение при обновлении, права доступа."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
src = sys.argv[1]
work = os.path.join(os.path.dirname(src), "work_model")
os.environ["APPDATA"] = tempfile.mkdtemp()

from PySide6.QtCore import QEventLoop, QTimer, Qt, QItemSelectionModel
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow

if os.path.exists(work):
    shutil.rmtree(work)
shutil.copytree(src, work)
w = MainWindow(work)
w.resize(1200, 700)
w.move(-6000, 100)
w.show()
F = w.active_folder()
ok = True


def wait(cond, timeout=6.0):
    l = QEventLoop()
    t = QTimer()
    t.setInterval(50)
    el = [0.0]

    def tick():
        el[0] += 0.05
        if cond() or el[0] > timeout:
            l.quit()
    t.timeout.connect(tick)
    t.start()
    l.exec()
    t.stop()
    return cond()


def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and bool(cond)


def names():
    return [e.name for e in F.model._rows]


wait(lambda: F.model.rowCount(F.tree.rootIndex()) > 5)
n0 = F.model.rowCount(F.tree.rootIndex())

# слежение: файл появился снаружи
open(os.path.join(work, "снаружи.txt"), "w").write("x")
check("новый файл снаружи появился сам", wait(lambda: "снаружи.txt" in names()))
# выделение сохраняется при обновлении
idx = F.model.index(os.path.join(work, "заметки.txt"))
F.view().setCurrentIndex(idx)
F.view().selectionModel().select(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
open(os.path.join(work, "ещё один.txt"), "w").write("y")
wait(lambda: "ещё один.txt" in names())
check("выделение сохранилось после обновления", [os.path.basename(p) for p in F.selected_paths()] == ["заметки.txt"])
os.remove(os.path.join(work, "снаружи.txt"))
check("удалённый снаружи файл исчез", wait(lambda: "снаружи.txt" not in names()))

# сортировка: числа как числа, папки сверху
os.makedirs(os.path.join(work, "Сорт"), exist_ok=True)
for n in ("файл10.txt", "файл2.txt", "файл1.txt"):
    open(os.path.join(work, "Сорт", n), "w").write("z" * len(n))
F.navigate(os.path.join(work, "Сорт"))
wait(lambda: F.model.rowCount(F.tree.rootIndex()) == 3)
check("естественный порядок: 1, 2, 10", names() == ["файл1.txt", "файл2.txt", "файл10.txt"])
F.sort_by(0, Qt.DescendingOrder)
check("по убыванию: 10, 2, 1", names() == ["файл10.txt", "файл2.txt", "файл1.txt"])
F.sort_by(1, Qt.AscendingOrder)
check("по размеру", names()[0] == "файл1.txt" or names()[0] == "файл2.txt")
F.sort_by(0, Qt.AscendingOrder)

# папки выше файлов
F.navigate(work)
wait(lambda: F.model.rowCount(F.tree.rootIndex()) > 5)
flags = [e.is_dir for e in F.model._rows]
check("папки идут выше файлов", flags == sorted(flags, reverse=True))

# Этот компьютер
F.navigate("")
wait(lambda: F.model.rowCount(F.tree.rootIndex()) > 0)
check("«Этот компьютер»: диски", F.model.rowCount(F.tree.rootIndex()) > 0 and all(e.drive for e in F.model._rows))
F.navigate(work)

# нет доступа / нет папки
errs = []
F.model.error.connect(errs.append)
check("несуществующая папка не открывается", F.navigate(os.path.join(work, "нет такой")) is False)

# скрытые и фильтр
F.navigate(work)
wait(lambda: F.model.rowCount(F.tree.rootIndex()) > 5)
n = F.model.rowCount(F.tree.rootIndex())
w.a_hidden.setChecked(True)
check("скрытые показались", F.model.rowCount(F.tree.rootIndex()) == n + 1)
w.a_hidden.setChecked(False)
F.show_filter()
F.filter_edit.setText("картинка 3")
check("фильтр по имени", F.model.rowCount(F.tree.rootIndex()) == 1)
F.filter_edit.clear()
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
