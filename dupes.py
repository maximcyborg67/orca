"""Поиск одинаковых файлов (по содержимому, а не по имени). Ничего не удаляет само: лишнее отправляется в корзину
только по кнопке и после подтверждения."""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QHeaderView, QMessageBox, QCheckBox, QSpinBox, QAbstractItemView, QFileIconProvider)
from PySide6.QtCore import QFileInfo

from util import fmt_size, plural

HEAD = 64 * 1024


def _hash(path, limit=None):
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        if limit:
            h.update(f.read(limit))
        else:
            while True:
                b = f.read(1024 * 1024)
                if not b:
                    break
                h.update(b)
    return h.digest()


class DupWorker(QThread):
    progress = Signal(str)
    found = Signal(list)         # группа: [(путь, размер, время), …]
    finished_scan = Signal(bool, int)

    def __init__(self, roots, min_size, include_hidden, whole_pc=False):
        super().__init__()
        self.roots, self.min_size, self.include_hidden, self.whole_pc = roots, min_size, include_hidden, whole_pc
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        by_size = {}
        count = 0
        stack = [] if self.whole_pc else list(self.roots)
        try:
            if self.whole_pc:          # по всему ПК: кандидатов (одинаковый размер) берём из индекса, диски заново не обходим
                import fileindex
                self.progress.emit("Беру из индекса файлы с одинаковым размером…")
                by_size = fileindex.candidates_by_size(self.min_size, self.include_hidden)
                count = sum(len(v) for v in by_size.values())
            while stack and not self._cancel:
                cur = stack.pop()
                try:
                    it = os.scandir(cur)
                except OSError:
                    continue
                with it:
                    for e in it:
                        if self._cancel:
                            break
                        try:
                            st = e.stat(follow_symlinks=False)
                            if not self.include_hidden and getattr(st, "st_file_attributes", 0) & 0x2:
                                continue
                            if e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                            elif e.is_file(follow_symlinks=False) and st.st_size >= self.min_size:
                                by_size.setdefault(st.st_size, []).append((e.path, st.st_mtime))
                                count += 1
                                if count % 500 == 0:
                                    self.progress.emit(f"Просмотрено файлов: {count}")
                        except OSError:
                            continue
            cands = {s: v for s, v in by_size.items() if len(v) > 1}
            total = sum(len(v) for v in cands.values())
            done = 0
            def head_of(item, size):
                try:
                    if os.path.getsize(item[0]) != size:        # индекс мог устареть
                        return None
                    return _hash(item[0], HEAD)
                except OSError:
                    return None

            def full_of(item):
                try:
                    return _hash(item[0])
                except OSError:
                    return None

            with ThreadPoolExecutor(max_workers=4) as pool:         # диск читает несколько потоков сразу: заметно быстрее
                for size, items in sorted(cands.items(), key=lambda kv: -kv[0]):
                    if self._cancel:
                        break
                    heads = {}
                    for item, h in zip(items, pool.map(lambda it: head_of(it, size), items)):
                        if h is not None:
                            heads.setdefault(h, []).append(item)
                    done += len(items)
                    for group in heads.values():
                        if len(group) < 2 or self._cancel:
                            continue
                        full = {}
                        for item, h in zip(group, pool.map(full_of, group)):
                            if h is not None:
                                full.setdefault(h, []).append(item)
                        for g in full.values():
                            if len(g) > 1:
                                self.found.emit([(p, size, mt) for p, mt in g])
                    self.progress.emit(f"Сверка: {done} из {total} кандидатов…")
        finally:
            self.finished_scan.emit(self._cancel, count)


class DuplicatesDialog(QDialog):
    def __init__(self, host, roots, whole_pc=False):
        super().__init__(host)
        self.host = host
        self.roots = roots
        self.whole_pc = whole_pc
        self.setWindowTitle("Поиск дубликатов")
        self.resize(900, 600)
        self._icons = QFileIconProvider()
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.lbl = QLabel("Ищем по всему компьютеру (по индексу; системные папки Windows и Program Files пропускаются)"
                          if whole_pc else "Ищем в: " + "; ".join(roots))
        self.lbl.setWordWrap(True)
        top.addWidget(self.lbl, 1)
        top.addWidget(QLabel("не меньше"))
        self.min_kb = QSpinBox()
        self.min_kb.setRange(0, 10_000_000)
        self.min_kb.setValue(100)
        self.min_kb.setSuffix(" КБ")
        top.addWidget(self.min_kb)
        self.chk_hidden = QCheckBox("скрытые")
        top.addWidget(self.chk_hidden)
        self.btn_scan = QPushButton("Искать")
        self.btn_scan.clicked.connect(self.start)
        top.addWidget(self.btn_scan)
        lay.addLayout(top)
        self.status = QLabel("Нажмите «Искать». Файлы сравниваются по содержимому, имена не важны.")
        lay.addWidget(self.status)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Файл", "Размер", "Изменён", "Папка"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        hd = self.tree.header()
        hd.setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.setColumnWidth(0, 320)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 130)
        hd.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tree.itemChanged.connect(lambda *_: self._update_sel())
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        b1 = QPushButton("Отметить лишние, оставить старейший")
        b1.clicked.connect(lambda: self._auto_mark(oldest=True))
        b2 = QPushButton("…оставить новейший")
        b2.clicked.connect(lambda: self._auto_mark(oldest=False))
        b3 = QPushButton("Снять отметки")
        b3.clicked.connect(lambda: self._auto_mark(None))
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch(1)
        self.sel_lbl = QLabel("")
        row.addWidget(self.sel_lbl)
        self.btn_del = QPushButton("Отмеченные — в корзину")
        self.btn_del.clicked.connect(self._delete)
        row.addWidget(self.btn_del)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.worker = None
        self._groups = 0
        self._saved = 0

    def start(self):
        self.stop()
        self.tree.clear()
        self._groups = 0
        self._saved = 0
        self.btn_scan.setEnabled(False)
        self.status.setText("Идёт поиск…")
        w = DupWorker(self.roots, self.min_kb.value() * 1024, self.chk_hidden.isChecked(), self.whole_pc)
        w.progress.connect(self.status.setText)
        w.found.connect(self._add_group)
        w.finished_scan.connect(self._done)
        self.worker = w
        w.start()

    def stop(self):
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(3000)
            self.worker = None

    def _add_group(self, items):
        self.tree.blockSignals(True)
        size = items[0][1]
        n = len(items)
        head = QTreeWidgetItem([f"{n} {plural(n, 'копия', 'копии', 'копий')} по {fmt_size(size)}", "", "", ""])
        head.setFlags(Qt.ItemIsEnabled)
        f = head.font(0)
        f.setBold(True)
        head.setFont(0, f)
        self.tree.addTopLevelItem(head)
        for p, s, mt in sorted(items, key=lambda x: x[2]):
            it = QTreeWidgetItem([os.path.basename(p), fmt_size(s),
                                  datetime.fromtimestamp(mt).strftime("%d.%m.%Y %H:%M"), os.path.dirname(p)])
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
            it.setData(0, Qt.UserRole, p)
            it.setData(1, Qt.UserRole, s)
            it.setData(2, Qt.UserRole, mt)
            it.setIcon(0, self._icons.icon(QFileInfo(p)))
            head.addChild(it)
        head.setExpanded(True)
        self._groups += 1
        self._saved += size * (n - 1)
        self.tree.blockSignals(False)

    def _done(self, cancelled, count):
        self.btn_scan.setEnabled(True)
        if cancelled:
            self.status.setText("Поиск остановлен.")
        elif self._groups == 0:
            self.status.setText(f"Дубликатов не найдено (просмотрено файлов: {count}).")
        else:
            self.status.setText(f"Найдено групп: {self._groups}. Лишние копии занимают {fmt_size(self._saved)}. "
                                f"Ничего не отмечено: выберите сами или нажмите кнопку автоотметки.")

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                yield head, head.child(j)

    def _auto_mark(self, oldest):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            kids = [head.child(j) for j in range(head.childCount())]
            kids.sort(key=lambda k: k.data(2, Qt.UserRole))
            keep = None if oldest is None else (kids[0] if oldest else kids[-1])
            for k in kids:
                k.setCheckState(0, Qt.Checked if (oldest is not None and k is not keep) else Qt.Unchecked)
        self.tree.blockSignals(False)
        self._update_sel()

    def _checked(self):
        return [it for _h, it in self._items() if it.checkState(0) == Qt.Checked]

    def _update_sel(self):
        ch = self._checked()
        size = sum(it.data(1, Qt.UserRole) for it in ch)
        self.sel_lbl.setText(f"Отмечено: {len(ch)} ({fmt_size(size)})" if ch else "")
        # защита: в каждой группе должна остаться хотя бы одна неотмеченная копия
        self.btn_del.setEnabled(bool(ch))

    def _delete(self):
        ch = self._checked()
        if not ch:
            return
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            if all(head.child(j).checkState(0) == Qt.Checked for j in range(head.childCount())):
                QMessageBox.warning(self, "Дубликаты",
                                    "В одной из групп отмечены ВСЕ копии — так файл пропадёт целиком. "
                                    "Снимите отметку хотя бы с одной копии в каждой группе.")
                return
        size = sum(it.data(1, Qt.UserRole) for it in ch)
        r = QMessageBox.question(self, "Дубликаты",
                                 f"Переместить в корзину {len(ch)} {plural(len(ch), 'файл', 'файла', 'файлов')} "
                                 f"({fmt_size(size)})?\nИх можно будет восстановить из корзины.")
        if r != QMessageBox.Yes:
            return
        paths = [it.data(0, Qt.UserRole) for it in ch]
        self.host.ops.delete(paths, permanent=False, confirm=False)   # уже спросили выше
        for it in ch:
            it.setDisabled(True)
            it.setCheckState(0, Qt.Unchecked)
        self.status.setText(f"Отправлено в корзину: {len(paths)}.")

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)
