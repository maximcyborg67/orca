"""Проверка поиска по вложенным папкам."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
src_dir = sys.argv[1]
work = os.path.join(os.path.dirname(src_dir), "work_search")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="prov_appdata_")

from PySide6.QtCore import QTimer, QEventLoop
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow

if os.path.exists(work):
    shutil.rmtree(work)
shutil.copytree(src_dir, work)
w = MainWindow(work)
w.move(-6000, 100)
w.show()
F = w.active_folder()
ok_all = True


def wait(cond, timeout=10.0):
    loop = QEventLoop()
    t = QTimer()
    t.setInterval(40)
    el = [0.0]

    def tick():
        el[0] += 0.04
        if cond() or el[0] > timeout:
            loop.quit()
    t.timeout.connect(tick)
    t.start()
    loop.exec()
    t.stop()
    return cond()


def check(name, cond):
    global ok_all
    print(("PASS  " if cond else "FAIL  ") + name)
    ok_all = ok_all and bool(cond)


def search(text):
    F.show_search()
    F.search_edit.setText(text)
    F.start_search()
    wait(lambda: not F._searching)
    return F.results.topLevelItemCount()


wait(lambda: False, 1.0)
n = search("картинка")
check(f"поиск «картинка» нашёл 4 файла (нашёл {n})", n == 4 and F.search_active)
check("показан список результатов", F.stack.currentWidget() is F.results)
n = search("image png")
check(f"два слова: image + png → 4 (нашёл {n})", n == 4)
n = search("0399")
paths = [F.results.topLevelItem(i).data(0, 0x100) for i in range(F.results.topLevelItemCount())]
check(f"поиск во вложенной папке (нашёл {n})", n == 1 and "Проекты" in paths[0])
n = search("*.txt")
check(f"подстановка *.txt → 400 (нашёл {n})", n == 400)
check("строка статуса", "Найдено: 400" in F.status_text())
n = search("такого-нет-zzz")
check("ничего не найдено", n == 0 and "Ничего не найдено" in F.status_text())

search("0399")
F.results.topLevelItem(0).setSelected(True)
check("выделение в результатах видно как selected_paths", len(F.selected_paths()) == 1)
target = F.selected_paths()[0]
F.show_in_folder(target)
check("«Показать в папке»: поиск закрыт, папка открыта",
      not F.search_active and F.path.lower().endswith("проекты"))
wait(lambda: F._select_after is None, 3)
cur = F.view().currentIndex()
check("«Показать в папке»: файл выделен", cur.isValid() and os.path.samefile(F.model.filePath(cur), target))

search("файл")
F.close_search()
check("Esc закрывает поиск и возвращает список", not F.search_active and F.stack.currentWidget() is not F.results)

# удаление из результатов
w.ops.silent = True
n = search("0398")
F.results.topLevelItem(0).setSelected(True)
p = F.selected_paths()[0]
F.delete(permanent=True)
w.ops.wait_all()
wait(lambda: F.results.topLevelItemCount() == 0, 5)
check("удалённый файл пропал из результатов и с диска", not os.path.exists(p) and F.results.topLevelItemCount() == 0)

# отмена долгого поиска
F.navigate(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
F.show_search()
F.search_edit.setText("py")
F.start_search()
F.close_search()
wait(lambda: False, 0.5)
check("отмена поиска не роняет программу", not F.search_active)

print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok_all else "ЕСТЬ ОШИБКИ")
app.quit()
