"""Своё окно «Свойства»: файл, папка (размер считается в фоне), атрибуты, несколько объектов, диск."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
work = sys.argv[1]
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["ORCA_NO_POPUP"] = "1"

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
import propsdlg
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


def texts(d):
    return " | ".join(l.text() for l in d.findChildren(propsdlg.QLabel))


w = MainWindow(work)
w.move(-6000, 100)
w.show()
pump(600)

f = os.path.join(work, "props_файл.txt")
open(f, "w", encoding="utf-8").write("x" * 2000)

d = propsdlg.PropsDialog(w, [f])
pump(200)
t = texts(d)
check("файл: есть размер в байтах", "2\u00a0000 байт" in t or "2000 байт" in t)
check("файл: есть дата изменения", " г., " in t)
check("файл: расположение", work in t)

# атрибуты
check("атрибуты сначала выключены", not d.ck_ro.isChecked() and not d.ck_hid.isChecked())
d.ck_ro.setChecked(True)
d.apply()
check("«Только чтение» включилось на диске", bool(propsdlg.get_attrs(f) & propsdlg.FILE_ATTRIBUTE_READONLY))
d.ck_ro.setChecked(False)
d.apply()
check("«Только чтение» выключилось", not (propsdlg.get_attrs(f) & propsdlg.FILE_ATTRIBUTE_READONLY))
d.close()

# папка
exp_files = exp_dirs = exp_size = 0
for r, ds, fs in os.walk(work):
    exp_dirs += len(ds)
    for n in fs:
        exp_files += 1
        exp_size += os.path.getsize(os.path.join(r, n))
d = propsdlg.PropsDialog(w, [work])
for _ in range(40):
    pump(100)
    if "считаю" not in d.size_lbl.text():
        break
check("папка: размер посчитан в фоне", "считаю" not in d.size_lbl.text())
check("папка: размер верный", str(exp_size).replace(",", "") in d.size_lbl.text().replace("\u00a0", "").replace(" ", "")
      or f"{exp_size:,}".replace(",", "\u00a0") in d.size_lbl.text())
check("папка: число файлов и папок верное", f"{exp_files} " in d.cont_lbl.text() and f"{exp_dirs} " in d.cont_lbl.text())
d.close()  # закрыть, пока можно прервать подсчёт

# несколько объектов
d = propsdlg.PropsDialog(w, [f, work])
check("несколько объектов: атрибуты недоступны", not d.ck_ro.isEnabled())
d.close()

# диск
d = propsdlg.PropsDialog(w, ["C:\\"])
t = texts(d)
check("диск: свободно и ёмкость", "Свободно" in t and "Ёмкость" in t)
d.close()

# из окна программы
F = w.active_folder()
F.navigate(work)
pump(500)
F.properties()
pump(300)
dlgs = [x for x in w.findChildren(propsdlg.PropsDialog)]
check("Alt+Enter открывает наше окно", len(dlgs) >= 1)
for x in dlgs:
    x.close()

w.close()
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
