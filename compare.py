"""Сравнение двух папок (левой и правой панели): что есть только с одной стороны и что отличается. Копирование —
по кнопке, через обычные операции Windows (спросит про замену файлов)."""
import hashlib
import os
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal, QFileInfo
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QHeaderView, QCheckBox, QAbstractItemView, QFileIconProvider)

from util import fmt_size

TOL = 2.0     # допуск по времени (у FAT округляется до 2 с)


def walk(root, include_hidden):
    out = {}
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                    if not include_hidden and getattr(st, "st_file_attributes", 0) & 0x2:
                        continue
                    rel = os.path.relpath(e.path, root)
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                        out[rel.lower()] = (rel, e.path, True, 0, st.st_mtime)
                    else:
                        out[rel.lower()] = (rel, e.path, False, st.st_size, st.st_mtime)
                except OSError:
                    continue
    return out


def _file_hash(path):
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.digest()


def compare_trees(left, right, by_content=False, include_hidden=False, cancel=lambda: False):
    """Возвращает (только слева, только справа, отличаются, число одинаковых)."""
    a = walk(left, include_hidden)
    b = walk(right, include_hidden)
    only_l, only_r, diff, same = [], [], [], 0
    for k, va in a.items():
        if cancel():
            break
        vb = b.get(k)
        if vb is None:
            only_l.append(va)
        elif va[2] or vb[2]:
            if va[2] != vb[2]:
                diff.append((va, vb))
            else:
                same += 1
        else:
            same_size = va[3] == vb[3]
            same_time = abs(va[4] - vb[4]) <= TOL
            if same_size and same_time:
                same += 1
            elif same_size and by_content:
                try:
                    if _file_hash(va[1]) == _file_hash(vb[1]):
                        same += 1
                        continue
                except OSError:
                    pass
                diff.append((va, vb))
            else:
                diff.append((va, vb))
    for k, vb in b.items():
        if k not in a:
            only_r.append(vb)
    only_l.sort(key=lambda x: x[0].lower())
    only_r.sort(key=lambda x: x[0].lower())
    diff.sort(key=lambda p: p[0][0].lower())
    return only_l, only_r, diff, same


class CompareWorker(QThread):
    done = Signal(list, list, list, int)

    def __init__(self, left, right, by_content, include_hidden):
        super().__init__()
        self.args = (left, right, by_content, include_hidden)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        l, r, d, s = compare_trees(*self.args, cancel=lambda: self._cancel)
        self.done.emit(l, r, d, s)


class CompareDialog(QDialog):
    def __init__(self, host, left, right):
        super().__init__(host)
        self.host, self.left, self.right = host, left, right
        self.setWindowTitle("Сравнение папок")
        self.resize(980, 640)
        self._icons = QFileIconProvider()
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Слева: {left}"))
        lay.addWidget(QLabel(f"Справа: {right}"))
        row = QHBoxLayout()
        self.chk_content = QCheckBox("сравнивать содержимое (медленнее, но точнее)")
        self.chk_hidden = QCheckBox("скрытые")
        self.btn = QPushButton("Сравнить")
        self.btn.clicked.connect(self.start)
        row.addWidget(self.chk_content)
        row.addWidget(self.chk_hidden)
        row.addStretch(1)
        row.addWidget(self.btn)
        lay.addLayout(row)
        self.status = QLabel("")
        lay.addWidget(self.status)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Файл", "Слева", "Справа", "Время слева", "Время справа"])
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        hd = self.tree.header()
        hd.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2):
            self.tree.setColumnWidth(c, 90)
        for c in (3, 4):
            self.tree.setColumnWidth(c, 130)
        lay.addWidget(self.tree, 1)
        row2 = QHBoxLayout()
        bl = QPushButton("Отметить «только слева» и «новее слева»")
        bl.clicked.connect(lambda: self._mark("l"))
        br = QPushButton("Отметить «только справа» и «новее справа»")
        br.clicked.connect(lambda: self._mark("r"))
        bn = QPushButton("Снять отметки")
        bn.clicked.connect(lambda: self._mark(None))
        for b in (bl, br, bn):
            row2.addWidget(b)
        row2.addStretch(1)
        lay.addLayout(row2)
        row3 = QHBoxLayout()
        row3.addStretch(1)
        self.btn_to_r = QPushButton("Отмеченное слева → скопировать направо")
        self.btn_to_r.clicked.connect(lambda: self._copy("l2r"))
        self.btn_to_l = QPushButton("Отмеченное справа → скопировать налево")
        self.btn_to_l.clicked.connect(lambda: self._copy("r2l"))
        row3.addWidget(self.btn_to_l)
        row3.addWidget(self.btn_to_r)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        row3.addWidget(close)
        lay.addLayout(row3)
        self.worker = None
        self.start()

    def start(self):
        self.stop()
        self.tree.clear()
        self.btn.setEnabled(False)
        self.status.setText("Сравниваю…")
        w = CompareWorker(self.left, self.right, self.chk_content.isChecked(), self.chk_hidden.isChecked())
        w.done.connect(self._done)
        self.worker = w
        w.start()

    def stop(self):
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(5000)
            self.worker = None

    @staticmethod
    def _t(mt):
        return datetime.fromtimestamp(mt).strftime("%d.%m.%Y %H:%M") if mt else ""

    def _section(self, title, count):
        it = QTreeWidgetItem([f"{title}: {count}", "", "", "", ""])
        it.setFlags(Qt.ItemIsEnabled)
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        self.tree.addTopLevelItem(it)
        it.setExpanded(True)
        return it

    def _done(self, only_l, only_r, diff, same):
        self.btn.setEnabled(True)
        self.tree.blockSignals(True)
        if only_l:
            sec = self._section("Только слева", len(only_l))
            for rel, p, is_dir, size, mt in only_l[:5000]:
                it = QTreeWidgetItem([rel + ("\\" if is_dir else ""), "" if is_dir else fmt_size(size), "—",
                                      self._t(mt), ""])
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked)
                it.setData(0, Qt.UserRole, ("l", p, rel))
                it.setIcon(0, self._icons.icon(QFileInfo(p)))
                sec.addChild(it)
        if only_r:
            sec = self._section("Только справа", len(only_r))
            for rel, p, is_dir, size, mt in only_r[:5000]:
                it = QTreeWidgetItem([rel + ("\\" if is_dir else ""), "—", "" if is_dir else fmt_size(size), "",
                                      self._t(mt)])
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked)
                it.setData(0, Qt.UserRole, ("r", p, rel))
                it.setIcon(0, self._icons.icon(QFileInfo(p)))
                sec.addChild(it)
        if diff:
            sec = self._section("Отличаются", len(diff))
            for va, vb in diff[:5000]:
                newer = "l" if va[4] > vb[4] + TOL else ("r" if vb[4] > va[4] + TOL else "=")
                mark = {"l": "  ← новее слева", "r": "  → новее справа", "=": ""}[newer]
                it = QTreeWidgetItem([va[0] + mark, "" if va[2] else fmt_size(va[3]), "" if vb[2] else fmt_size(vb[3]),
                                      self._t(va[4]), self._t(vb[4])])
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked)
                it.setData(0, Qt.UserRole, ("d", va[1], vb[1], va[0], newer))
                sec.addChild(it)
        self.tree.blockSignals(False)
        self.status.setText(
            f"Только слева: {len(only_l)}, только справа: {len(only_r)}, отличаются: {len(diff)}, "
            f"одинаковых: {same}. Ничего не отмечено — выберите сами или кнопками ниже.")

    def _each(self):
        for i in range(self.tree.topLevelItemCount()):
            sec = self.tree.topLevelItem(i)
            for j in range(sec.childCount()):
                yield sec.child(j)

    def _mark(self, side):
        for it in self._each():
            d = it.data(0, Qt.UserRole)
            on = False
            if side == "l":
                on = d[0] == "l" or (d[0] == "d" and d[4] == "l")
            elif side == "r":
                on = d[0] == "r" or (d[0] == "d" and d[4] == "r")
            it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)

    def _copy(self, direction):
        """Копирует отмеченное из одной папки в другую, сохраняя вложенность. Вопросы о замене задаёт Windows."""
        ops = self.host.ops
        dst_root = self.right if direction == "l2r" else self.left
        want = "l" if direction == "l2r" else "r"
        groups = {}
        for it in self._each():
            if it.checkState(0) != Qt.Checked:
                continue
            d = it.data(0, Qt.UserRole)
            if d[0] == want:
                src, rel = d[1], d[2]
            elif d[0] == "d":
                src = d[1] if direction == "l2r" else d[2]
                rel = d[3]
            else:
                continue
            if os.path.isdir(src):
                continue
            dst_dir = os.path.dirname(os.path.join(dst_root, rel))
            groups.setdefault(dst_dir, []).append(src)
        if not groups:
            self.status.setText("Нет отмеченного для этого направления.")
            return
        n = 0
        for dst_dir, files in groups.items():
            try:
                os.makedirs(dst_dir, exist_ok=True)
            except OSError:
                continue
            ops.transfer(files, dst_dir, copy=True)
            n += len(files)
        self.status.setText(f"Копирую файлов: {n}. Когда закончится, нажмите «Сравнить» ещё раз.")

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)
