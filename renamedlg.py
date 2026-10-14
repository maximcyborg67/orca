"""Массовое переименование: правила (заменить / приставка / окончание / номер / регистр), перед применением —
таблица «было → стало» с проверкой на повторы и запрещённые символы. Применяется одной кнопкой, отменяется Ctrl+Z."""
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QHeaderView)

BAD = '<>:"/\\|?*'
MODES = ["Заменить текст", "Добавить в начало", "Добавить в конец (перед расширением)", "Пронумеровать",
         "Весь текст — ПРОПИСНЫМИ", "Весь текст — строчными", "Каждое Слово С Заглавной", "Убрать пробелы по краям и двойные"]


def apply_rule(names, mode, a="", b="", start=1, digits=3, keep_ext=True, regex=False, sep=" "):
    """Новые имена для списка старых (чистая функция — удобно проверять)."""
    out = []
    for i, old in enumerate(names):
        stem, ext = os.path.splitext(old) if keep_ext else (old, "")
        if mode == 0:
            if regex:
                try:
                    stem = re.sub(a, b, stem)
                except re.error:
                    pass
            elif a:
                stem = stem.replace(a, b)
        elif mode == 1:
            stem = a + stem
        elif mode == 2:
            stem = stem + a
        elif mode == 3:
            n = str(start + i).zfill(digits)
            stem = f"{a}{n}{b}" if (a or b) else f"{stem}{sep}{n}"      # «Фото_001» или «имя 001»
        elif mode == 4:
            stem = stem.upper()
        elif mode == 5:
            stem = stem.lower()
        elif mode == 6:
            stem = stem.title()
        elif mode == 7:
            stem = re.sub(r"\s{2,}", " ", stem).strip()
        out.append(stem + ext)
    return out


def problems(old_paths, new_names):
    """Список проблем: одинаковые новые имена, запрещённые символы, пустые имена, занятые имена."""
    probs = {}
    seen = {}
    olds = {os.path.normcase(p) for p in old_paths}
    for p, n in zip(old_paths, new_names):
        folder = os.path.dirname(p)
        key = (os.path.normcase(folder), n.lower())
        if not n or n in (".", "..") or any(c in BAD for c in n) or n.endswith(".") or n != n.strip():
            probs[p] = "недопустимое имя"
        elif key in seen:
            probs[p] = "такое имя уже выбрано для другого файла"
        else:
            seen[key] = p
            target = os.path.join(folder, n)
            if os.path.normcase(target) != os.path.normcase(p) and os.path.exists(target) \
                    and os.path.normcase(target) not in olds:
                probs[p] = "в папке уже есть такой файл"
    return probs


def do_rename(pairs):
    """Переименовать пары (старый_путь, новый_путь) безопасно: через временные имена, чтобы обмены не конфликтовали.
    Возвращает (успешно_переименованные [(старый, новый)], список_ошибок)."""
    done, errors = [], []
    temps = []
    for old, new in pairs:
        if os.path.normcase(old) == os.path.normcase(new) and old == new:
            continue
        tmp = os.path.join(os.path.dirname(old), f"~orca_{abs(hash(old)) % 10**9}.tmp")
        try:
            os.rename(old, tmp)
            temps.append((tmp, old, new))
        except OSError as e:
            errors.append(f"{os.path.basename(old)}: {e.strerror}")
    for tmp, old, new in temps:
        try:
            os.rename(tmp, new)
            done.append((old, new))
        except OSError as e:
            errors.append(f"{os.path.basename(old)}: {e.strerror}")
            try:
                os.rename(tmp, old)               # вернуть как было
            except OSError:
                pass
    return done, errors


class RenameDialog(QDialog):
    def __init__(self, parent, paths, on_done=None):
        super().__init__(parent)
        self.paths = [os.path.normpath(p) for p in paths]
        self.on_done = on_done
        self.setWindowTitle(f"Переименовать: {len(paths)} шт.")
        self.resize(780, 560)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        form.addRow("Что сделать:", self.mode)
        self.a = QLineEdit()
        self.b = QLineEdit()
        self.lab_a = QLabel("Найти:")
        self.lab_b = QLabel("Заменить на:")
        form.addRow(self.lab_a, self.a)
        form.addRow(self.lab_b, self.b)
        row = QHBoxLayout()
        self.start = QSpinBox()
        self.start.setRange(0, 999999)
        self.start.setValue(1)
        self.digits = QSpinBox()
        self.digits.setRange(1, 8)
        self.digits.setValue(3)
        row.addWidget(QLabel("Начать с:"))
        row.addWidget(self.start)
        row.addWidget(QLabel("цифр:"))
        row.addWidget(self.digits)
        self.keep_ext = QCheckBox("не трогать расширение")
        self.keep_ext.setChecked(True)
        self.regex = QCheckBox("регулярное выражение")
        row.addWidget(self.keep_ext)
        row.addWidget(self.regex)
        row.addStretch(1)
        self.opts = QLabel()
        form.addRow(self.opts, row)
        lay.addLayout(form)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Было", "Станет", ""])
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(2, 220)
        lay.addWidget(self.table, 1)
        self.info = QLabel("")
        lay.addWidget(self.info)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.ok = QPushButton("Переименовать")
        self.ok.clicked.connect(self._apply)
        c = QPushButton("Отмена")
        c.clicked.connect(self.reject)
        btns.addWidget(self.ok)
        btns.addWidget(c)
        lay.addLayout(btns)
        for w in (self.a, self.b):
            w.textChanged.connect(self._refresh)
        for w in (self.start, self.digits):
            w.valueChanged.connect(self._refresh)
        for w in (self.keep_ext, self.regex):
            w.toggled.connect(self._refresh)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def _mode_changed(self):
        m = self.mode.currentIndex()
        self.lab_a.setText({0: "Найти:", 1: "Текст в начало:", 2: "Текст в конец:", 3: "Перед номером (необязательно):"}.get(m, "—"))
        self.lab_b.setText({0: "Заменить на:", 3: "После номера (необязательно):"}.get(m, "—"))
        self.a.setEnabled(m in (0, 1, 2, 3))
        self.b.setEnabled(m in (0, 3))
        self.start.setEnabled(m == 3)
        self.digits.setEnabled(m == 3)
        self.regex.setEnabled(m == 0)
        self._refresh()

    def new_names(self):
        olds = [os.path.basename(p) for p in self.paths]
        return apply_rule(olds, self.mode.currentIndex(), self.a.text(), self.b.text(), self.start.value(),
                          self.digits.value(), self.keep_ext.isChecked(), self.regex.isChecked())

    def _refresh(self):
        news = self.new_names()
        probs = problems(self.paths, news)
        self.table.clear()
        changed = 0
        for p, n in zip(self.paths, news):
            old = os.path.basename(p)
            it = QTreeWidgetItem([old, n, probs.get(p, "")])
            if p in probs:
                it.setForeground(2, Qt.red)
                it.setForeground(1, Qt.red)
            elif n != old:
                changed += 1
            self.table.addTopLevelItem(it)
        self.ok.setEnabled(bool(changed) and not probs)
        self.info.setText(f"Изменится: {changed} из {len(news)}" + (f". Проблем: {len(probs)} — исправьте правило" if probs else ""))

    def _apply(self):
        news = self.new_names()
        pairs = [(p, os.path.join(os.path.dirname(p), n)) for p, n in zip(self.paths, news) if os.path.basename(p) != n]
        done, errors = do_rename(pairs)
        self.result_pairs = done
        self.errors = errors
        if self.on_done:
            self.on_done(done, errors)
        self.accept()
