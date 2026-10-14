"""Быстрый просмотр (пробел) и цветные метки."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
src = sys.argv[1]
work = os.path.join(os.path.dirname(src), "work_ql")
vid = os.path.join(os.path.dirname(src), "viddir", "тест видео.mp4")
os.environ["APPDATA"] = tempfile.mkdtemp()

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow

if os.path.exists(work):
    shutil.rmtree(work)
shutil.copytree(src, work)
shutil.copy(vid, work)
w = MainWindow(work)
w.resize(1200, 700)
w.move(-6000, 100)
w.show()
F = w.active_folder()
ok = True


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and bool(cond)


def select(name):
    idx = F.model.index(os.path.join(work, name))
    F.view().setCurrentIndex(idx)
    F.view().selectionModel().select(idx, F.view().selectionModel().SelectionFlag.ClearAndSelect |
                                     F.view().selectionModel().SelectionFlag.Rows)
    pump(200)


pump(1500)
ql = w.quicklook
select("картинка 1.jpg")
QTest.keyClick(F.view(), Qt.Key_Space)
pump(300)
check("пробел открывает просмотр картинки", ql.isVisible() and ql.stack.currentWidget() is ql.image and ql._pm is not None)
select("заметки.txt")
pump(300)
check("стрелка/выбор другого файла обновляет просмотр (текст)", ql.isVisible() and ql.stack.currentWidget() is ql.text
      and "Русский текст" in ql.text.toPlainText())
select("Фото")
pump(300)
check("папка показывает состав", ql.stack.currentWidget() is ql.text)
select("тест видео.mp4")
for _ in range(40):
    pump(100)
    if ql.stack.currentWidget() is ql.image:
        break
check("видео: миниатюра от Windows", ql.stack.currentWidget() is ql.image)
QTest.keyClick(F.view(), Qt.Key_Escape)
pump(200)
check("Esc закрывает просмотр", not ql.isVisible())
QTest.keyClick(F.view(), Qt.Key_Space)
pump(200)
check("пробел снова открывает", ql.isVisible())
QTest.keyClick(F.view(), Qt.Key_Space)
pump(200)
check("пробел закрывает", not ql.isVisible())

# метки
select("заметки.txt")
p = os.path.join(work, "заметки.txt")
idx = F.model.index(p)
before = F.model.data(idx, Qt.DecorationRole).cacheKey()
w.set_tags([p], "red")
after = F.model.data(idx, Qt.DecorationRole).cacheKey()
check("метка меняет значок", before != after)
check("метка сохраняется в настройках", w.settings["tags"].get(os.path.normpath(p).lower()) == "red")
F.model.setData(idx, "переименован.txt")
pump(300)
np_ = os.path.join(work, "переименован.txt")
check("метка переехала при переименовании", w.tags.get(os.path.normpath(np_).lower()) == "red"
      and os.path.normpath(p).lower() not in w.tags)
w.set_tags([np_], None)
check("метку можно убрать", not w.tags)
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
