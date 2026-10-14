"""Окно: поиск «По всему ПК» через индекс (учебные файлы, диски не обходятся)."""
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="prov_idx2_"); os.environ["ORCA_NO_INDEX"] = "1"
root = os.path.join(tempfile.gettempdir(), "orca_idx_ui"); shutil.rmtree(root, ignore_errors=True)
os.makedirs(os.path.join(root, "Глубоко", "ещё глубже")); 
open(os.path.join(root, "Глубоко", "ещё глубже", "секретный отчёт.docx"), "w").write("x")
open(os.path.join(root, "Глубоко", "отчёт 2.txt"), "w").write("x")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv); app.setStyle("Fusion")
import theme; theme.apply(app, "dark")
import fileindex
fileindex.ROOTS = [root]
from mainwin import MainWindow
w = MainWindow(root); w.move(-6000, 100); w.show()
w.settings["use_everything"] = False       # здесь проверяется собственный индекс Orca, а не Everything
def pump(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n)
F = w.active_folder(); pump(500)
F.show_search(scope=1); F.search_edit.setText("отчёт"); F.start_search(); pump(300)
check("без индекса поиск «по всему ПК» не стартует (пишет, что индекс строится)", not F.search_active)
for _ in range(50):
    pump(200)
    if not w.file_index.building: break
check("индекс собрался, строка статуса показывает число файлов", "файлов" in w.lbl_index.text())
F.show_search(scope=1); F.search_edit.setText("отчёт"); F.start_search(); pump(800)
names = sorted(F.results.topLevelItem(i).text(0) for i in range(F.results.topLevelItemCount()))
check(f"по всему ПК найдено: {names}", names == ["отчёт 2.txt", "секретный отчёт.docx"])
check("переключатель «В этой папке» возвращает обычный поиск", F.scope.currentIndex() == 1)
F.scope.setCurrentIndex(0); pump(800)
check("в этой папке тоже находит (живой обход)", F.results.topLevelItemCount() == 2)
F.close_search(); pump(100)
check("Esc закрывает строку поиска", not F.search_row.isVisible())
w.file_index.stop()
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ"); sys.exit(0 if ok else 1)
