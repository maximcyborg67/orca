"""Версия 1.2: версия/журнал/«О программе», вернуть вкладку, недавние, размер папки, суммы, маска, подтверждение, новое окно."""
import hashlib
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
src = sys.argv[1]
work = os.path.join(os.path.dirname(src), "work_v12")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["ORCA_NO_POPUP"] = "1"

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
import about
import version
from mainwin import MainWindow
from util import folder_size
import hashdlg

ok = True


def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and bool(cond)


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


# ---- версия и журнал ----
parts = version.VERSION.split(".")
check("версия вида 1.2.0", len(parts) == 3 and all(p.isdigit() for p in parts))
txt = about.changelog_text()
check("журнал изменений найден и начинается с текущей версии", f"## {version.VERSION}" in txt.split("\n## ")[0] + "\n## "
      or txt.split("\n## ")[1].startswith(version.VERSION))
check("«последняя версия» берётся целиком", about.latest_section(txt).startswith(f"## {version.VERSION}")
      and "## 1.1.0" not in about.latest_section(txt))

if os.path.exists(work):
    shutil.rmtree(work)
shutil.copytree(src, work)
w = MainWindow(work)
w.resize(1200, 700)
w.move(-6000, 100)
w.show()
w.ops.silent = True
F = w.active_folder()
pump(1000)

d = about.AboutDialog(w)
labels = " ".join(l.text() for l in d.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
check("«О программе» показывает версию и дату", version.VERSION in labels and version.RELEASE_DATE in labels)
cd = about.ChangelogDialog(w)
check("окно «Что нового» открывается", cd.findChildren(__import__("PySide6.QtWidgets", fromlist=["QTextBrowser"]).QTextBrowser))

# ---- вернуть закрытую вкладку ----
pane = w.active_pane()
t2 = os.path.join(work, "Фото")
pane.add_tab(t2)
pump(300)
n = pane.count()
pane.close_tab(pane.count() - 1)
check("вкладка закрылась", pane.count() == n - 1)
w.reopen_tab()
pump(300)
check("Ctrl+Shift+T возвращает ту же папку", pane.count() == n and os.path.normcase(pane.current_path()) == os.path.normcase(os.path.normpath(t2)))
w.closed_tabs.clear()
w.reopen_tab()
check("если закрытых нет — ничего не ломается", pane.count() == n)

# ---- недавние ----
F.navigate(os.path.join(work, "Проекты"))
F.navigate(os.path.join(work, "Документы"))
check("недавние помнят папки (новые сверху)", [os.path.basename(p) for p in w.recent[:2]] == ["Документы", "Проекты"])
for i in range(12):
    os.makedirs(os.path.join(work, f"т{i}"), exist_ok=True)
    F.navigate(os.path.join(work, f"т{i}"))
check("список недавних не длиннее 8", len(w.recent) == 8)
w.sidebar.build()
heads = [w.sidebar.topLevelItem(i).text(0) for i in range(w.sidebar.topLevelItemCount())]
check("в боковой панели есть раздел «Недавние»", "НЕДАВНИЕ" in heads)

# ---- размер папки ----
F.navigate(work)
pump(600)
total, files, dirs = folder_size([os.path.join(work, "Проекты")])
real_total = sum(os.path.getsize(os.path.join(r, f)) for r, _d, fs in os.walk(os.path.join(work, "Проекты")) for f in fs)
check(f"размер папки посчитан верно ({total} Б, {files} файлов)", total == real_total and files >= 399 and dirs == 0)
F.calc_size([os.path.join(work, "Проекты")])
w.ops.wait_all()
check("размер папки из меню считается в фоне", getattr(F, "last_size", None) == real_total)

# ---- контрольные суммы ----
p = os.path.join(work, "заметки.txt")
res = hashdlg.compute(p)
data = open(p, "rb").read()
check("MD5 / SHA-1 / SHA-256 совпадают с эталоном",
      res["MD5"] == hashlib.md5(data).hexdigest() and res["SHA-1"] == hashlib.sha1(data).hexdigest()
      and res["SHA-256"] == hashlib.sha256(data).hexdigest())
hd = hashdlg.HashDialog(w, p)
for _ in range(60):
    pump(50)
    if hd.sums:
        break
hd.expect.setText(res["SHA-256"].upper())
pump(100)
check("сверка: верная сумма — «Совпало»", "Совпало" in hd.verdict.text() and "НЕ" not in hd.verdict.text())
hd.expect.setText("0" * 64)
pump(100)
check("сверка: неверная сумма — «НЕ совпало»", "НЕ совпало" in hd.verdict.text())
hd.close()

# ---- выделение по маске / инверсия ----
F.navigate(work)
pump(600)
total_rows = len(F.model._rows)
n1 = F.select_by_mask("*.jpg")
sel = [os.path.basename(x) for x in F.selected_paths()]
check("маска *.jpg выделяет только jpg", n1 and n1 == len(sel) and all(s.lower().endswith(".jpg") for s in sel))
n2 = F.select_by_mask("картинка 1; *.txt")
sel2 = {os.path.basename(x) for x in F.selected_paths()}
check("несколько масок через «;» (слово без * — часть имени)", "картинка 1.jpg" in sel2 and "заметки.txt" in sel2)
F.select_by_mask("*.jpg")
F.invert_selection()
inv = [os.path.basename(x) for x in F.selected_paths()]
check("инверсия: выделено всё, кроме jpg", len(inv) == total_rows - n1 and not any(s.lower().endswith(".jpg") for s in inv))

# ---- подтверждение удаления ----
asked = []
w.ops.silent = False
w.ops._confirm = lambda text: (asked.append(text), False)[1]
victim = os.path.join(work, "скрипт.py")
w.ops.always_confirm = False
w.ops.delete([victim])
w.ops.wait_all()
check("по умолчанию один файл удаляется без вопроса (в корзину)", not asked and not os.path.exists(victim))
open(victim, "w").write("x")
w.ops.always_confirm = True
w.ops.delete([victim])
check("с включённым «Всегда спрашивать» вопрос задан, а на «Нет» файл цел", len(asked) == 1 and os.path.exists(victim))

# ---- новое окно: настройки не перезаписывает ----
os.environ["ORCA_SECONDARY"] = "1"
w2 = MainWindow(work)
check("второе окно знает, что оно дополнительное", w2.secondary)
w2.close()
del os.environ["ORCA_SECONDARY"]
w.ops.silent = True
w.close()
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
