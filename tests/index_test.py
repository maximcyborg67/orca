"""Индекс файлов, поиск по всему ПК и дубликаты по индексу — на учебных файлах (диски не обходятся)."""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="prov_idx_")
root = os.path.join(tempfile.gettempdir(), "orca_idx_data")
shutil.rmtree(root, ignore_errors=True)
os.environ["ORCA_NO_INDEX"] = "1"

from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)
import fileindex

ok = True


def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("PASS  " if cond else "FAIL  ") + name)


for d in ("Фото", "Фото/сюда", "Документы", "Бэкап", "$Recycle.Bin"):
    os.makedirs(os.path.join(root, d), exist_ok=True)
blob = os.urandom(300 * 1024)
for p in ("Фото/отпуск.jpg", "Бэкап/отпуск копия.jpg", "Документы/другое имя.bin"):
    open(os.path.join(root, p), "wb").write(blob)
open(os.path.join(root, "Фото/сюда/уникальный.txt"), "w").write("x" * 1000)
open(os.path.join(root, "Документы/Отчёт 2026.TXT"), "w").write("hello")
open(os.path.join(root, "Фото/такой же размер.bin"), "wb").write(os.urandom(300 * 1024))      # тот же размер, другое содержимое
open(os.path.join(root, "$Recycle.Bin/мусор.jpg"), "wb").write(blob)                           # корзина не индексируется
open(os.path.join(root, ".скрытый"), "w").write("s")
os.system(f'attrib +h "{os.path.join(root, ".скрытый")}"')

fileindex.ROOTS = [root]
check("индекса ещё нет", fileindex.info() is None)
t = time.time()
b = fileindex.IndexBuilder()
res = {}
b.done.connect(lambda c, n: res.update(c=c, n=n))
b.run()
check(f"индекс построен ({res.get('n')} записей, {time.time() - t:.2f} с)", res.get("c") is False and res.get("n", 0) >= 10)
check("info() читает число записей", fileindex.info() and fileindex.info()[0] == res["n"])


def search(text, hidden=False):
    w = fileindex.IndexSearchWorker(text, hidden)
    got = []
    w.found.connect(lambda rows: got.extend(rows))
    w.run()
    return [os.path.basename(r[0]) for r in got]


check("поиск по части имени, русские буквы", sorted(search("отпуск")) == ["отпуск копия.jpg", "отпуск.jpg"])
check("регистр не важен (ОТЧЁТ → Отчёт 2026.TXT)", search("ОТЧЁТ") == ["Отчёт 2026.TXT"])
check("несколько слов", search("отпуск копия") == ["отпуск копия.jpg"])
check("подстановка *.txt", sorted(search("*.txt")) == ["Отчёт 2026.TXT", "уникальный.txt"])
check("папки находятся", "Фото" in search("фото"))
check("скрытые не показываются", search("скрытый") == [] and search("скрытый", True) == [".скрытый"])
check("корзина не в индексе", "мусор.jpg" not in search("мусор"))
check("ничего не найдено", search("zzzzzz") == [])
os.remove(os.path.join(root, "Фото/сюда/уникальный.txt"))
check("удалённый после сборки файл не попадает в результаты", search("уникальный") == [])

c = fileindex.candidates_by_size(100 * 1024, False)
sizes = {s: sorted(os.path.basename(p) for p, _ in v) for s, v in c.items()}
check("кандидаты: файлы одного размера (3 копии + «такой же размер»)", len(c) == 1 and len(list(sizes.values())[0]) == 4)

from dupes import DupWorker
w = DupWorker([], 100 * 1024, False, whole_pc=True)
groups = []
w.found.connect(lambda g: groups.append(sorted(os.path.basename(p) for p, _s, _m in g)))
w.run()
check("дубликаты по индексу: одна группа из 3 копий, «такой же размер» не попал",
      groups == [sorted(["отпуск.jpg", "отпуск копия.jpg", "другое имя.bin"])])
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
sys.exit(0 if ok else 1)
