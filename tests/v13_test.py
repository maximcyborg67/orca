"""Версия 1.3: массовое переименование, быстрые команды, копирование имён."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
src = sys.argv[1]
work = os.path.join(os.path.dirname(src), "work_v13")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["ORCA_NO_POPUP"] = "1"

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
import palette
import renamedlg as rd
import vfs
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


# ---- правила переименования (чистые функции) ----
names = ["a b.txt", "Фото 1.JPG", "x.tar.gz"]
check("заменить текст", rd.apply_rule(names, 0, " ", "_") == ["a_b.txt", "Фото_1.JPG", "x.tar.gz"])
check("регулярное выражение", rd.apply_rule(["file12.txt"], 0, r"\d+", "#", regex=True) == ["file#.txt"])
check("приставка и окончание (перед расширением)", rd.apply_rule(["a.txt"], 1, "Мой_") == ["Мой_a.txt"]
      and rd.apply_rule(["a.txt"], 2, "_v2") == ["a_v2.txt"])
check("нумерация «Фото_001»", rd.apply_rule(["x.jpg", "y.jpg"], 3, "Фото_", "", 1, 3) == ["Фото_001.jpg", "Фото_002.jpg"])
check("нумерация без текста — к имени", rd.apply_rule(["x.jpg"], 3, "", "", 5, 2) == ["x 05.jpg"])
check("регистр", rd.apply_rule(["аБв.txt"], 4)[0] == "АБВ.txt" and rd.apply_rule(["АБВ.TXT"], 5)[0] == "абв.TXT")
check("расширение не меняется при смене регистра", rd.apply_rule(["Abc.JPG"], 5) == ["abc.JPG"])

if os.path.exists(work):
    shutil.rmtree(work)
os.makedirs(work)
for n in ("один.txt", "два.txt", "три.txt"):
    open(os.path.join(work, n), "w", encoding="utf-8").write(n)
P = lambda n: os.path.join(work, n)

probs = rd.problems([P("один.txt"), P("два.txt")], ["одно.txt", "одно.txt"])
check("одинаковые новые имена — проблема", len(probs) == 1)
check("запрещённые символы — проблема", rd.problems([P("один.txt")], ["а:б.txt"]))
check("занятое имя — проблема", rd.problems([P("один.txt")], ["два.txt"]))
check("обмен именами двух файлов допустим (оба переименовываются)", not rd.problems(
    [P("один.txt"), P("два.txt")], ["два.txt", "один.txt"]))
done, errs = rd.do_rename([(P("один.txt"), P("два.txt")), (P("два.txt"), P("один.txt"))])
check("обмен имён выполняется через временные имена, без потерь",
      not errs and open(P("один.txt"), encoding="utf-8").read() == "два.txt"
      and open(P("два.txt"), encoding="utf-8").read() == "один.txt")
check("временные файлы не остаются", not [f for f in os.listdir(work) if f.startswith("~orca_")])

# ---- окно: F2 на нескольких файлах + отмена ----
w = MainWindow(work)
w.resize(1100, 650)
w.move(-6000, 100)
w.show()
w.ops.silent = True
F = w.active_folder()
pump(1000)
paths = [P("один.txt"), P("два.txt"), P("три.txt")]
dlg = rd.RenameDialog(w, paths, None)
dlg.mode.setCurrentIndex(3)
dlg.a.setText("Док_")
pump(100)
check("таблица предпросмотра показывает новые имена", dlg.table.topLevelItem(0).text(1) == "Док_001.txt"
      and dlg.ok.isEnabled())
calls = []


def on_done(pairs, errors):
    calls.append((pairs, errors))
    def back():
        rd.do_rename([(n, o) for o, n in pairs if os.path.exists(n) and not os.path.exists(o)])
    w.ops.push_undo("массовое переименование", back)


dlg.on_done = on_done
dlg._apply()
check("переименование применено", sorted(os.listdir(work)) == ["Док_001.txt", "Док_002.txt", "Док_003.txt"] and calls)
w.ops.undo()
check("Ctrl+Z возвращает все имена", sorted(os.listdir(work)) == sorted(["один.txt", "два.txt", "три.txt"]))

# ---- копировать имена ----
F.navigate(work)
pump(600)
F.select_by_mask("*.txt")
F.copy_names()
txt = QApplication.clipboard().text().split("\n")
check("«Копировать имена» кладёт в буфер только имена", sorted(txt) == sorted(["один.txt", "два.txt", "три.txt"]))

# ---- быстрые команды ----
items = palette.collect(w)
titles = [t for t, _k, _a in items]
check("в быстрых командах есть вкладки, поиск и дубликаты", "Новая вкладка" in titles and "Найти дубликаты" in titles
      and "Поиск в папке и во вложенных" in titles)
p = palette.Palette(w)
p.edit.setText("дубл")
check("фильтр по части слова", p.list.count() >= 1 and "дубликаты" in p.list.item(0).text().lower())
p.edit.setText("zzzнетттакого")
check("ничего не найдено — пустой список", p.list.count() == 0)
p.close()

w.close()
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
