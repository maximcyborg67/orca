"""Окно «Настройки»: свои горячие клавиши для любого действия + основные параметры программы."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import settings as cfg


class SettingsDialog(QDialog):
    def __init__(self, win, tab=0):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Настройки Orca")
        self.resize(760, 640)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._build_general()
        self._build_hotkeys()
        self.tabs.setCurrentIndex(tab)
        row = QHBoxLayout()
        row.addStretch(1)
        b = QPushButton("Закрыть")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)

    # ---------------- общие ----------------
    def _build_general(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        s = self.win.settings

        lay.addWidget(QLabel("<b>При запуске</b>"))
        self.r_restore = QRadioButton("Открыть то, что было открыто в прошлый раз")
        self.r_home = QRadioButton("Всегда открывать домашнюю папку")
        self.r_folder = QRadioButton("Всегда открывать эту папку:")
        cur = s.get("startup", "restore")
        {"restore": self.r_restore, "home": self.r_home, "folder": self.r_folder}.get(cur, self.r_restore).setChecked(True)
        lay.addWidget(self.r_restore)
        lay.addWidget(self.r_home)
        row = QHBoxLayout()
        row.addWidget(self.r_folder)
        self.startup_path = QLineEdit(s.get("startup_path", ""))
        row.addWidget(self.startup_path, 1)
        br = QPushButton("Выбрать…")
        br.clicked.connect(self._pick_folder)
        row.addWidget(br)
        lay.addLayout(row)
        for r in (self.r_restore, self.r_home, self.r_folder):
            r.toggled.connect(self._save_startup)
        self.startup_path.editingFinished.connect(self._save_startup)

        lay.addWidget(QLabel("<b>Вид</b>"))
        form = QFormLayout()
        self.cb_mode = QComboBox()
        for key, name in (("details", "Подробно"), ("compact", "Компактно"), ("icons", "Значки")):
            self.cb_mode.addItem(name, key)
        self.cb_mode.setCurrentIndex(max(0, self.cb_mode.findData(s.get("mode", "details"))))
        self.cb_mode.currentIndexChanged.connect(
            lambda: self.win.settings.__setitem__("mode", self.cb_mode.currentData()) or self.win._set_mode(self.cb_mode.currentData()))
        form.addRow("Вид папок по умолчанию:", self.cb_mode)
        self.cb_theme = QComboBox()
        self.cb_theme.addItem("Тёмная", "dark")
        self.cb_theme.addItem("Светлая", "light")
        self.cb_theme.setCurrentIndex(max(0, self.cb_theme.findData(s.get("theme", "dark"))))
        self.cb_theme.currentIndexChanged.connect(lambda: self.win._set_theme(self.cb_theme.currentData()))
        form.addRow("Тема:", self.cb_theme)
        lay.addLayout(form)

        lay.addWidget(QLabel("<b>Поведение</b>"))
        self.ck_hidden = QCheckBox("Показывать скрытые файлы")
        self.ck_hidden.setChecked(self.win.show_hidden)
        self.ck_hidden.toggled.connect(self.win.a_hidden.setChecked)
        self.ck_confirm = QCheckBox("Всегда спрашивать перед удалением (даже одного файла)")
        self.ck_confirm.setChecked(self.win.ops.always_confirm)
        self.ck_confirm.toggled.connect(self.win.a_confirm.setChecked)
        self.ck_ev = QCheckBox("Искать по всему компьютеру через Everything (если она установлена)")
        self.ck_ev.setChecked(bool(s.get("use_everything", True)))
        self.ck_ev.toggled.connect(self.win.a_ev.setChecked)
        for c in (self.ck_hidden, self.ck_confirm, self.ck_ev):
            lay.addWidget(c)

        lay.addWidget(QLabel("<b>Служебное</b>"))
        row2 = QHBoxLayout()
        b1 = QPushButton("Открыть папку с настройками и журналами")
        b1.clicked.connect(lambda: os.startfile(cfg.DIR) if os.path.isdir(cfg.DIR) else None)
        row2.addWidget(b1)
        row2.addStretch(1)
        lay.addLayout(row2)
        lay.addStretch(1)
        self.tabs.addTab(w, "Общие")

    def _pick_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Папка, которая открывается при запуске", self.startup_path.text())
        if p:
            self.startup_path.setText(os.path.normpath(p))
            self.r_folder.setChecked(True)
            self._save_startup()

    def _save_startup(self):
        s = self.win.settings
        s["startup"] = "folder" if self.r_folder.isChecked() else ("home" if self.r_home.isChecked() else "restore")
        s["startup_path"] = self.startup_path.text().strip()

    # ---------------- горячие клавиши ----------------
    def _build_hotkeys(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Найти действие… (например, вкладка, поиск, метка)")
        self.filter.textChanged.connect(self._fill)
        top.addWidget(self.filter, 1)
        lay.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Действие", "Сочетание клавиш", "По умолчанию"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        hd = self.tree.header()
        hd.setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setColumnWidth(1, 170)
        self.tree.setColumnWidth(2, 150)
        self.tree.currentItemChanged.connect(self._pick)
        lay.addWidget(self.tree, 1)
        lay.addWidget(QLabel("Выберите действие, нажмите в поле ниже нужное сочетание и «Назначить»."))
        row = QHBoxLayout()
        self.edit = QKeySequenceEdit()
        self.edit.setMaximumSequenceLength(1)
        row.addWidget(self.edit, 1)
        self.b_set = QPushButton("Назначить")
        self.b_set.clicked.connect(self._assign)
        self.b_clear = QPushButton("Убрать клавишу")
        self.b_clear.clicked.connect(lambda: self._assign(clear=True))
        self.b_def = QPushButton("По умолчанию")
        self.b_def.clicked.connect(self._default)
        for b in (self.b_set, self.b_clear, self.b_def):
            row.addWidget(b)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.note = QLabel("")
        row2.addWidget(self.note, 1)
        b_all = QPushButton("Сбросить все клавиши")
        b_all.clicked.connect(self._reset_all)
        row2.addWidget(b_all)
        lay.addLayout(row2)
        self.tabs.addTab(w, "Горячие клавиши")
        self._fill("")

    def _fill(self, text=""):
        words = (text or "").lower().split()
        keep = self.tree.currentItem().data(0, Qt.UserRole) if self.tree.currentItem() else None
        self.tree.clear()
        for hid in sorted(self.win.hotkey_actions, key=lambda h: self.win.hotkey_title(h).lower()):
            title = self.win.hotkey_title(hid)
            if not all(w in title.lower() for w in words):
                continue
            cur = self.win.hotkey_actions[hid].shortcut().toString()
            dflt = QKeySequence(self.win.hotkey_defaults.get(hid, "")).toString()
            it = QTreeWidgetItem([title, cur or "—", dflt or "—"])
            it.setData(0, Qt.UserRole, hid)
            if cur != dflt:
                f = it.font(1)
                f.setBold(True)
                it.setFont(1, f)
            self.tree.addTopLevelItem(it)
            if hid == keep:
                self.tree.setCurrentItem(it)

    def _hid(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def _pick(self, *_):
        hid = self._hid()
        if hid:
            self.edit.setKeySequence(self.win.hotkey_actions[hid].shortcut())
            self.note.setText("")

    def _assign(self, clear=False):
        hid = self._hid()
        if not hid:
            self.note.setText("Сначала выберите действие в списке.")
            return
        seq = "" if clear else self.edit.keySequence().toString()
        if not clear and not seq:
            self.note.setText("Нажмите нужное сочетание клавиш в поле.")
            return
        other = self.win.set_hotkey(hid, seq)
        if other:
            r = QMessageBox.question(self, "Клавиша занята",
                                     f"Сочетание {seq} уже назначено на «{self.win.hotkey_title(other)}».\n"
                                     "Отобрать его у того действия и назначить сюда?")
            if r != QMessageBox.Yes:
                return
            self.win.set_hotkey(hid, seq, steal=True)
        self.note.setText(f"Готово: «{self.win.hotkey_title(hid)}» — {seq or 'без клавиши'}.")
        self._fill(self.filter.text())

    def _default(self):
        hid = self._hid()
        if not hid:
            return
        d = self.win.hotkey_defaults.get(hid, "")
        other = self.win.set_hotkey(hid, d)
        if other:
            self.win.set_hotkey(hid, d, steal=True)
        self.edit.setKeySequence(QKeySequence(d))
        self.note.setText("Возвращена клавиша по умолчанию.")
        self._fill(self.filter.text())

    def _reset_all(self):
        if QMessageBox.question(self, "Горячие клавиши", "Вернуть ВСЕ горячие клавиши к стандартным?") == QMessageBox.Yes:
            self.win.reset_hotkeys()
            self.note.setText("Все клавиши сброшены.")
            self._fill(self.filter.text())
