"""Контрольные суммы файла (MD5, SHA-1, SHA-256): считаются в фоне; можно вставить ожидаемую сумму и сверить."""
import hashlib
import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QVBoxLayout)

from util import fmt_size

ALGOS = (("MD5", "md5"), ("SHA-1", "sha1"), ("SHA-256", "sha256"))


class HashWorker(QThread):
    progress = Signal(int)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            hs = {name: hashlib.new(algo) for name, algo in ALGOS}
            size = max(1, os.path.getsize(self.path))
            read = 0
            with open(self.path, "rb") as f:
                while not self._cancel:
                    b = f.read(4 * 1024 * 1024)
                    if not b:
                        break
                    for h in hs.values():
                        h.update(b)
                    read += len(b)
                    self.progress.emit(int(read * 100 / size))
            if not self._cancel:
                self.done.emit({k: h.hexdigest() for k, h in hs.items()})
        except OSError as e:
            self.failed.emit(e.strerror or str(e))


def compute(path):
    """Синхронно (для тестов): {'MD5': …, 'SHA-1': …, 'SHA-256': …}."""
    hs = {name: hashlib.new(algo) for name, algo in ALGOS}
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b""):
            for h in hs.values():
                h.update(b)
    return {k: h.hexdigest() for k, h in hs.items()}


class HashDialog(QDialog):
    def __init__(self, parent, path):
        super().__init__(parent)
        self.path = path
        self.sums = {}
        self.setWindowTitle("Контрольные суммы")
        self.resize(760, 300)
        lay = QVBoxLayout(self)
        name = QLabel(f"<b>{os.path.basename(path)}</b>  ·  {fmt_size(os.path.getsize(path))}")
        name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(name)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        lay.addWidget(self.bar)
        grid = QGridLayout()
        self.edits = {}
        for r, (title, _a) in enumerate(ALGOS):
            grid.addWidget(QLabel(title), r, 0)
            e = QLineEdit("считаю…")
            e.setReadOnly(True)
            self.edits[title] = e
            grid.addWidget(e, r, 1)
            b = QPushButton("Копировать")
            b.clicked.connect(lambda _=False, t=title: QApplication.clipboard().setText(self.edits[t].text()))
            grid.addWidget(b, r, 2)
        lay.addLayout(grid)
        lay.addWidget(QLabel("Сверить с ожидаемой суммой (вставьте её сюда):"))
        self.expect = QLineEdit()
        self.expect.setPlaceholderText("например, SHA-256 с сайта, откуда скачан файл")
        self.expect.textChanged.connect(self._check)
        lay.addWidget(self.expect)
        self.verdict = QLabel("")
        lay.addWidget(self.verdict)
        row = QHBoxLayout()
        row.addStretch(1)
        c = QPushButton("Закрыть")
        c.clicked.connect(self.close)
        row.addWidget(c)
        lay.addLayout(row)
        self.worker = HashWorker(path)
        self.worker.progress.connect(self.bar.setValue)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(lambda m: self.verdict.setText("Не удалось прочитать файл: " + m))
        self.worker.start()

    def _done(self, sums):
        self.sums = sums
        for k, v in sums.items():
            self.edits[k].setText(v)
        self.bar.setValue(100)
        self._check()

    def _check(self):
        want = self.expect.text().strip().lower().replace(" ", "")
        if not want:
            self.verdict.setText("")
            return
        if not self.sums:
            self.verdict.setText("Подождите, сумма ещё считается…")
            return
        hit = [k for k, v in self.sums.items() if v.lower() == want]
        if hit:
            self.verdict.setText(f"<span style='color:#3fb950'><b>Совпало</b> ({hit[0]}) — файл не изменён.</span>")
        else:
            self.verdict.setText("<span style='color:#f85149'><b>НЕ совпало</b> — файл другой или повреждён.</span>")

    def closeEvent(self, e):
        self.worker.cancel()
        self.worker.wait(5000)
        super().closeEvent(e)
