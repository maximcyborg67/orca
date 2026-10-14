"""Главное окно."""
import os
import subprocess
import sys

from PySide6.QtCore import Qt, QByteArray, QSize, QStorageInfo, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QMainWindow, QSplitter, QToolBar, QWidget, QSizePolicy, QLabel, QSlider,
                               QApplication, QMenu, QToolButton, QMessageBox)

import settings as cfg
import theme
import winfx
from fileindex import FileIndex
from folderview import FolderView
from infopanel import InfoPanel
from ops import Ops
from pane import Pane
from sidebar import Sidebar
from ui import G, icon_font
from util import fmt_size, norm_path


class MainWindow(QMainWindow):
    def __init__(self, start_path=None):
        super().__init__()
        self.settings = cfg.load()
        if self.settings.get("theme") not in ("dark", "light"):
            self.settings["theme"] = "dark"
        self.setWindowTitle("Orca")
        self.resize(1320, 820)
        self.setMinimumSize(760, 480)
        self.ops = Ops(self)
        self.ops.always_confirm = bool(self.settings.get("confirm_delete", False))
        self.file_index = FileIndex()
        self.ops.message.connect(lambda m: self.flash(m))
        self.secondary = bool(os.environ.get("ORCA_SECONDARY"))   # окно, открытое через Ctrl+N: настройки не перезаписывает
        self.closed_tabs = []                                      # недавно закрытые вкладки (Ctrl+Shift+T)
        self.recent = self.settings.setdefault("recent", [])       # недавние папки
        self.tags = self.settings.setdefault("tags", {})       # цветные метки: путь (в нижнем регистре) -> цвет
        self.quicklook = None
        self.hotkey_actions, self.hotkey_defaults, self._hk_count = {}, {}, {}
        self.mode = self.settings.get("mode", "details")
        self.show_hidden = bool(self.settings.get("show_hidden"))
        self._active = None
        self._closing = False

        # ----- части окна -----
        self.sidebar = Sidebar(self.settings.get("bookmarks", []), self.recent)
        self.sidebar.open_path.connect(self._sidebar_open)
        self.sidebar.open_new_tab.connect(lambda p: self.active_pane().add_tab(p))
        self.sidebar.files_dropped.connect(self._sidebar_drop)
        self.sidebar.bookmarks_changed.connect(lambda b: self.settings.update(bookmarks=list(b)))

        home = os.path.expanduser("~")
        startup = self.settings.get("startup", "restore")          # что открывать при запуске (меню «Настройки»)
        if startup == "home":
            t1 = [home]
        elif startup == "folder":
            t1 = [self.settings.get("startup_path") or home]
        else:
            t1 = self.settings.get("tabs1") or [home]
        if start_path:
            t1 = [start_path]
        self.pane1 = Pane(self, [p for p in t1 if p == "" or os.path.isdir(p)] or [""], self.mode)
        self.pane2 = Pane(self, [p for p in (self.settings.get("tabs2") or []) if os.path.isdir(p)]
                          or [os.path.expanduser("~")], self.mode)
        for pane in (self.pane1, self.pane2):
            pane.last_tab_closed.connect(self._last_tab_closed)
            pane.currentChanged.connect(lambda _=0: self._refresh_all())
        self.panes = QSplitter(Qt.Horizontal)
        self.panes.setChildrenCollapsible(False)
        self.panes.addWidget(self.pane1)
        self.panes.addWidget(self.pane2)
        self.pane2.setVisible(bool(self.settings.get("split")) and not start_path)
        self.preview = InfoPanel()
        self.preview.setVisible(bool(self.settings.get("show_preview")))
        self.sidebar.setVisible(bool(self.settings.get("show_sidebar", True)))

        self.main = QSplitter(Qt.Horizontal)
        self.main.setChildrenCollapsible(False)
        self.main.addWidget(self.sidebar)
        self.main.addWidget(self.panes)
        self.main.addWidget(self.preview)
        self.main.setStretchFactor(1, 1)
        sizes = self.settings.get("sizes_main") or [230, 860, 260]
        self.main.setSizes(sizes if len(sizes) == 3 else [230, 860, 260])
        self.setCentralWidget(self.main)

        self._active = self.pane1
        self._build_actions()
        self.apply_saved_hotkeys()                                  # свои клавиши из настроек
        self._build_toolbar()
        self._build_statusbar()
        self.file_index.changed.connect(self._index_status)
        self._index_status()

        from quicklook import QuickLook
        self.quicklook = QuickLook(self)
        QApplication.instance().focusChanged.connect(self._focus_changed)
        g = self.settings.get("geometry")
        if g:
            self.restoreGeometry(QByteArray.fromHex(g.encode()))
        self.mode_changed(None)
        self._refresh_all()
        QTimer.singleShot(0, lambda: self.active_folder().focus_view())

    # ---------- «хозяйские» функции, которые вызывают вкладки ----------
    def flash(self, msg, ms=4500):
        self.statusBar().showMessage(msg, ms)

    def wire(self, f):
        f.path_changed.connect(self._folder_path_changed)
        f.selection_changed.connect(self._folder_selection_changed)
        f.status_changed.connect(self._folder_status_changed)

    def active_pane(self):
        return self._active if (self._active and self._active.isVisible()) else self.pane1

    def active_folder(self):
        return self.active_pane().current_folder()

    def other_pane(self, f):
        if not self.pane2.isVisible():
            return None
        pane = self.pane2 if self.pane1.indexOf(f) >= 0 else self.pane1
        return pane

    def other_path(self, f):
        p = self.other_pane(f)
        if p is None:
            return None
        cur = p.current_folder()
        return cur.path if cur is not None and cur.path else None

    def open_in_other(self, f, path):
        p = self.other_pane(f)
        if p is not None and p.current_folder() is not None:
            p.current_folder().navigate(path)

    # ---------- быстрый просмотр, метки ----------
    def toggle_quicklook(self):
        if self.quicklook.isVisible():
            self.quicklook.hide_it()
            return
        f = self.active_folder()
        sel = f.selected_paths()
        if not sel:
            idx = f.view().currentIndex() if not f.search_active else None
            if idx is not None and idx.isValid():
                sel = [f.model.filePath(idx)]
        if sel:
            self.quicklook.show_for(os.path.normpath(sel[0]))
        else:
            self.flash("Выделите файл и нажмите пробел")

    def set_tags(self, paths, color):
        for p in paths:
            key = os.path.normpath(p).lower()
            if color:
                self.tags[key] = color
            else:
                self.tags.pop(key, None)
        self._refresh_icons()

    def tag_moved(self, old, new):
        o, n = os.path.normpath(old).lower(), os.path.normpath(new).lower()
        if o in self.tags:
            self.tags[n] = self.tags.pop(o)
            self._refresh_icons()

    def _refresh_icons(self):
        for pane in (self.pane1, self.pane2):
            for f in pane.folders():
                f.model.refresh_icons()

    def add_bookmark(self, path):
        self.sidebar.add_bookmark(path)
        self.flash("Добавлено в закладки")

    # ---------- недавние папки, закрытые вкладки, новое окно ----------
    def note_recent(self, path):
        """Запомнить папку в «Недавних» (обычные папки, не архивы)."""
        import vfs
        if not path or vfs.is_virtual(path) or len(path.rstrip("\\")) <= 2:
            return
        p = os.path.normpath(path)
        low = p.lower()
        self.recent[:] = [p] + [r for r in self.recent if r.lower() != low]
        del self.recent[8:]
        self.sidebar.recent_changed()

    def _palette(self):
        from palette import Palette
        Palette(self).exec()

    def _toggle_everything(self, on):
        self.settings["use_everything"] = on
        self.flash("Поиск по всему ПК — через Everything" if on else "Поиск по всему ПК — по индексу Orca")

    def remember_closed_tab(self, path):
        if path:
            self.closed_tabs.append(path)
            del self.closed_tabs[:-15]

    def goto_tab(self, n):
        """Ctrl+N: перейти на вкладку номер n в активной панели (9 — на последнюю)."""
        pane = self.active_pane()
        i = pane.count() - 1 if n >= 9 else n - 1
        if 0 <= i < pane.count():
            pane.setCurrentIndex(i)
            f = pane.current_folder()
            if f is not None:
                f.focus_view()
        else:
            self.flash(f"Вкладки с номером {n} нет")

    def reopen_tab(self):
        while self.closed_tabs:
            p = self.closed_tabs.pop()
            import vfs
            if vfs.isdir(p):
                self.active_pane().add_tab(p)
                self.flash(f"Вкладка возвращена: {os.path.basename(p) or p}")
                return
        self.flash("Закрытых вкладок нет")

    def _new_window(self):
        """Ещё одно окно Orca в текущей папке (настройки им не перезаписываются)."""
        p = self.active_folder().path or os.path.expanduser("~")
        env = dict(os.environ, ORCA_SECONDARY="1")
        cmd = [sys.executable, p] if getattr(sys, "frozen", False) else \
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), p]
        try:
            subprocess.Popen(cmd, env=env)
        except OSError as e:
            self.flash(f"Не удалось открыть окно: {e}")

    def _toggle_confirm_delete(self, on):
        self.ops.always_confirm = on
        self.settings["confirm_delete"] = on
        self.flash("Перед любым удалением Orca будет спрашивать" if on else "Подтверждение только для папок и 5+ файлов")

    def mode_changed(self, f):
        self.mode = (f.mode if f is not None else self.mode)
        if getattr(self, "act_mode", None):
            self.act_mode[self.mode].setChecked(True)
        self._update_zoom()

    def icon_size_changed(self, f):
        self.settings["icon_size"] = f.icon_size
        self._update_zoom()

    # ---------- действия ----------
    # ---------- свои горячие клавиши ----------
    def hotkey_title(self, hid):
        a = self.hotkey_actions[hid]
        base = a.property("base_tip") or hid
        return base + (" (дополнительная клавиша)" if "#" in hid else "")

    def _set_tip(self, a):
        """Подсказка кнопки: название + текущая клавиша (после переназначения обновляется)."""
        base = a.property("base_tip")
        if base:
            seq = a.shortcut().toString()
            a.setToolTip(base + (f"  ({seq})" if seq else ""))

    def set_hotkey(self, hid, seq, steal=False):
        """Назначить действию клавишу (пустая строка — убрать). Возвращает id действия-конкурента, если клавиша занята
        и steal=False; иначе None."""
        a = self.hotkey_actions[hid]
        seq = QKeySequence(seq).toString() if seq else ""
        if seq:
            for oid, oa in self.hotkey_actions.items():
                if oid != hid and oa.shortcut().toString() == seq:
                    if not steal:
                        return oid
                    oa.setShortcut(QKeySequence())
                    self._store_hotkey(oid)
                    self._set_tip(oa)
        a.setShortcut(QKeySequence(seq))
        self._set_tip(a)
        self._store_hotkey(hid)
        return None

    def _store_hotkey(self, hid):
        cur = self.hotkey_actions[hid].shortcut().toString()
        saved = self.settings.setdefault("hotkeys", {})
        if cur == QKeySequence(self.hotkey_defaults.get(hid, "")).toString():
            saved.pop(hid, None)
        else:
            saved[hid] = cur

    def reset_hotkeys(self):
        self.settings["hotkeys"] = {}
        for hid, a in self.hotkey_actions.items():
            a.setShortcut(QKeySequence(self.hotkey_defaults.get(hid, "")))
            self._set_tip(a)

    def apply_saved_hotkeys(self):
        for hid, seq in (self.settings.get("hotkeys") or {}).items():
            a = self.hotkey_actions.get(hid)
            if a is not None:
                a.setShortcut(QKeySequence(seq))
        for a in self.hotkey_actions.values():
            self._set_tip(a)

    def _act(self, text, shortcut, slot, glyph=None, tip=None, checkable=False):
        a = QAction(glyph or text, self)
        import re
        a.setProperty("base_tip", re.sub(r"\s*\([^)]*\)\s*$", "", (tip or text)).strip())
        n = self._hk_count.get(text, 0) + 1                      # реестр для окна «Настройки»
        self._hk_count[text] = n
        hid = text if n == 1 else f"{text} #{n}"
        a.setObjectName(hid)
        self.hotkey_actions[hid] = a
        self.hotkey_defaults[hid] = shortcut or ""
        a.setToolTip(tip or text + (f"  ({shortcut})" if shortcut else ""))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WindowShortcut)
        a.setCheckable(checkable)
        if checkable:
            a.toggled.connect(slot)
        else:
            a.triggered.connect(lambda _=False: slot())
        self.addAction(a)
        return a

    def _build_actions(self):
        F = self.active_folder
        self.a_newtab = self._act("Новая вкладка", "Ctrl+T", lambda: self.active_pane().add_tab(F().path), G["newtab"])
        self.a_closetab = self._act("Закрыть вкладку", "Ctrl+W", lambda: self.active_pane().close_tab(self.active_pane().currentIndex()))
        for n in range(1, 10):                      # Ctrl+1…9 — вкладка по номеру, Ctrl+9 — последняя (как в браузере)
            self._act(f"Вкладка {n}" if n < 9 else "Последняя вкладка", f"Ctrl+{n}",
                      (lambda k: lambda: self.goto_tab(k))(n))
        self._act("След. вкладка", "Ctrl+Tab", lambda: self.active_pane().next_tab(1))
        self._act("Пред. вкладка", "Ctrl+Shift+Tab", lambda: self.active_pane().next_tab(-1))
        self.a_newfolder = self._act("Создать папку", "Ctrl+Shift+N", lambda: F().new_folder(), G["newfolder"],
                                     tip="Создать папку  (F10 или Ctrl+Shift+N)")
        self._act("Создать папку", "F10", lambda: F().new_folder())
        self.a_cut = self._act("Вырезать", "Ctrl+X", lambda: F().cut(), G["cut"])
        self.a_copy = self._act("Копировать", "Ctrl+C", lambda: F().copy(), G["copy"])
        self.a_paste = self._act("Вставить", "Ctrl+V", lambda: F().paste(), G["paste"])
        self.a_rename = self._act("Переименовать", "F2", lambda: F().rename(), G["rename"])
        self.a_delete = self._act("В корзину", "Delete", lambda: F().delete(), G["delete"])
        self._act("Удалить навсегда", "Shift+Delete", lambda: F().delete(True))
        self.a_undo = self._act("Отменить", "Ctrl+Z", lambda: self.ops.undo(), G["undo"])
        self._act("Выделить всё", "", lambda: None)  # Ctrl+A обрабатывает сам список
        self._act("Свойства", "Alt+Return", lambda: F().properties())
        self._act("Назад", "Alt+Left", lambda: F().back())
        self._act("Вперёд", "Alt+Right", lambda: F().forward())
        self._act("Вверх", "Alt+Up", lambda: F().up())
        self._act("Вверх", "Backspace", lambda: F().up())
        self._act("Обновить", "F5", lambda: F().refresh())
        self._act("Домой", "Alt+Home", lambda: F().navigate(os.path.expanduser("~")))
        self._act("Адрес", "Ctrl+L", lambda: F().pathbar.begin_edit())
        self._act("Адрес", "F6", lambda: F().pathbar.begin_edit())
        self._act("Фильтр", "Ctrl+I", lambda: F().show_filter())
        self.a_search = self._act("Поиск по вложенным папкам", "Ctrl+F", lambda: F().show_search(), G["search"],
                                  tip="Поиск в папке и во вложенных  (Ctrl+F)")
        self._act("Поиск по всему ПК", "Ctrl+Shift+F", lambda: F().show_search(scope=1))
        self._act("Копировать путь", "Ctrl+Shift+C", lambda: F().copy_path())
        self._act("Терминал здесь", "F4", self._open_terminal)
        self._act("Метка", "Ctrl+M", lambda: F().show_tag_menu())
        self._act("Копия в другую панель", "F7", lambda: self._to_other(True))
        self._act("Перенос в другую панель", "F8", lambda: self._to_other(False))
        self._act("Закладка", "Ctrl+D", lambda: self.add_bookmark(F().path) if F().path else None)
        self._act("Вернуть закрытую вкладку", "Ctrl+Shift+T", self.reopen_tab)
        self._act("Новое окно", "Ctrl+N", self._new_window)
        self._act("Быстрые команды", "Ctrl+Shift+P", self._palette)
        self._act("Найти дубликаты", "", self._find_dupes)
        self._act("Сравнить папки двух панелей", "", self._compare_panes)
        self._act("Обновить индекс файлов", "", self.file_index.rebuild)
        self._act("Что нового", "", self._whatsnew)
        self._act("О программе", "", self._about)
        self._act("Горячие клавиши", "", self._show_keys)
        self._act("Настройки", "Ctrl+,", self._settings)
        self._act("Копировать имена файлов", "", lambda: F().copy_names())
        self._act("Выделить по маске", "Ctrl+S", lambda: F().select_by_mask())
        self._act("Инвертировать выделение", "Ctrl+Shift+I", lambda: F().invert_selection())

        self.act_mode = {}
        grp = QActionGroup(self)
        for i, (mode, glyph, name) in enumerate((("icons", G["icons"], "Значки"),
                                                  ("compact", G["compact"], "Компактно"),
                                                  ("details", G["details"], "Подробно"))):
            a = self._act(name, f"Ctrl+Shift+{i + 1}", (lambda m: lambda: self._set_mode(m))(mode), glyph,
                          tip=f"{name}  (Ctrl+Shift+{i + 1})")
            a.setCheckable(True)
            grp.addAction(a)
            self.act_mode[mode] = a
        self.a_hidden = self._act("Скрытые файлы", "Ctrl+H", self._toggle_hidden, G["hidden"],
                                  tip="Показывать скрытые файлы  (Ctrl+H)", checkable=True)
        self.a_hidden.setChecked(self.show_hidden)
        self.a_split = self._act("Две панели", "F3", self._toggle_split, G["split"],
                                 tip="Две панели  (F3)", checkable=True)
        self.a_split.setChecked(self.pane2.isVisible())
        self.a_preview = self._act("Сведения", "F11", self._toggle_preview, G["preview"],
                                   tip="Панель сведений  (F11)", checkable=True)
        self.a_preview.setChecked(self.preview.isVisible())
        self.a_sidebar = self._act("Боковая панель", "F9", self._toggle_sidebar, G["sidebar"],
                                   tip="Боковая панель  (F9)", checkable=True)
        self.a_sidebar.setChecked(self.sidebar.isVisible())
        self.a_filter = self._act("Фильтр", "", lambda: self.active_folder().show_filter(), G["filter"],
                                  tip="Фильтр по имени  (Ctrl+I)")

    def _build_toolbar(self):
        tb = QToolBar("Главная")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setContextMenuPolicy(Qt.PreventContextMenu)
        tb.setFont(icon_font(16))
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(Qt.TopToolBarArea, tb)
        for a in (self.a_newfolder,):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.a_cut, self.a_copy, self.a_paste, self.a_rename, self.a_delete, self.a_undo):
            tb.addAction(a)
        tb.addSeparator()
        for m in ("icons", "compact", "details"):
            tb.addAction(self.act_mode[m])
        tb.addSeparator()
        tb.addAction(self.a_search)
        tb.addAction(self.a_filter)
        tb.addAction(self.a_hidden)
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(sp)
        tb.addAction(self.a_sidebar)
        tb.addAction(self.a_split)
        tb.addAction(self.a_preview)
        more = QToolButton()
        more.setText(G["more"])
        more.setFont(icon_font(16))
        more.setToolTip("Ещё")
        more.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(more)
        th = m.addMenu("Тема оформления")
        grp = QActionGroup(th)
        self.theme_actions = {}
        for key, name in (("dark", "Тёмная"), ("light", "Светлая")):
            a = th.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.settings.get("theme", "dark") == key)
            grp.addAction(a)
            self.theme_actions[key] = a
            a.triggered.connect(lambda _=False, k=key: self._set_theme(k))
        m.addSeparator()
        m.addAction(self.hotkey_actions["Поиск по всему ПК"])
        self.a_ev = m.addAction("Искать через Everything (если установлена)")
        self.a_ev.setCheckable(True)
        self.a_ev.setChecked(bool(self.settings.get("use_everything", True)))
        self.a_ev.toggled.connect(self._toggle_everything)
        m.addAction("Обновить собственный индекс Orca").triggered.connect(self.file_index.rebuild)
        m.addAction(self.hotkey_actions["Быстрые команды"])
        m.addSeparator()
        m.addAction("Найти дубликаты в этой папке…").triggered.connect(self._find_dupes)
        m.addAction("Найти дубликаты по всему ПК…").triggered.connect(lambda: self._find_dupes(True))
        m.addAction("Сравнить папки двух панелей…").triggered.connect(self._compare_panes)
        m.addSeparator()
        m.addAction(self.hotkey_actions["Новое окно"])
        m.addAction(self.hotkey_actions["Вернуть закрытую вкладку"])
        self.a_confirm = m.addAction("Всегда спрашивать перед удалением")
        self.a_confirm.setCheckable(True)
        self.a_confirm.setChecked(self.ops.always_confirm)
        self.a_confirm.toggled.connect(self._toggle_confirm_delete)
        m.addSeparator()
        m.addAction(self.hotkey_actions["Настройки"])
        m.addAction("Горячие клавиши…").triggered.connect(self._show_keys)
        m.addAction("Что нового…").triggered.connect(self._whatsnew)
        import version
        m.addAction(f"О программе (версия {version.VERSION})").triggered.connect(self._about)
        more.setMenu(m)
        tb.addWidget(more)

    def _build_statusbar(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.lbl_status = QLabel("")
        self.lbl_status.setContentsMargins(8, 0, 0, 0)
        sb.addWidget(self.lbl_status, 1)
        self.lbl_index = QLabel("")
        self.lbl_index.setToolTip("Индекс файлов для поиска по всему ПК. Обновляется в фоне.")
        sb.addPermanentWidget(self.lbl_index)
        self.lbl_disk = QLabel("")
        sb.addPermanentWidget(self.lbl_disk)
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(32, 256)
        self.zoom.setFixedWidth(110)
        self.zoom.setToolTip("Размер значков (Ctrl + колесо мыши)")
        self.zoom.setValue(int(self.settings.get("icon_size", 96)))
        self.zoom.valueChanged.connect(self._zoom_slider)
        sb.addPermanentWidget(self.zoom)

    # ---------- переключатели ----------
    def _set_mode(self, mode):
        self.mode = mode
        self.settings["mode"] = mode
        self.active_folder().set_mode(mode)

    def _toggle_hidden(self, on):
        self.show_hidden = on
        for pane in (self.pane1, self.pane2):
            for f in pane.folders():
                f.apply_hidden()

    def _toggle_split(self, on):
        self.pane2.setVisible(on)
        if on:
            cur = self.pane1.current_path()
            f2 = self.pane2.current_folder()
            if f2 is not None and cur:
                f2.navigate(cur)
            total = self.panes.width()
            self.panes.setSizes([total // 2, total // 2])
            self._active = self.pane2
            f2.focus_view()
        else:
            self._active = self.pane1
            self.pane1.current_folder().focus_view()
        self._refresh_all()

    def _toggle_preview(self, on):
        self.preview.setVisible(on)
        self._update_preview()

    def _toggle_sidebar(self, on):
        self.sidebar.setVisible(on)

    def _index_status(self):
        self.lbl_index.setText(self.file_index.status_text())

    def _find_dupes(self, whole_pc=False):
        from dupes import DuplicatesDialog
        f = self.active_folder()
        if whole_pc:
            import fileindex
            if fileindex.info() is None:
                if not self.file_index.building:
                    self.file_index.rebuild()
                self.flash("Индекс файлов ещё строится (пара минут при первом запуске). Повторите чуть позже.")
                return
            dlg = DuplicatesDialog(self, [], whole_pc=True)
            dlg.show()
            self._dialogs = getattr(self, "_dialogs", [])
            self._dialogs.append(dlg)
            dlg.finished.connect(lambda *_: self._dialogs.remove(dlg) if dlg in self._dialogs else None)
            return
        sel = [p for p in f.selected_paths() if os.path.isdir(p)]
        roots = sel or ([f.path] if f.path and os.path.isdir(f.path) else [])
        if not roots:
            self.flash("Откройте папку или выделите папки, в которых искать дубликаты")
            return
        dlg = DuplicatesDialog(self, roots)
        dlg.show()
        self._dialogs = getattr(self, "_dialogs", [])
        self._dialogs.append(dlg)
        dlg.finished.connect(lambda *_: self._dialogs.remove(dlg) if dlg in self._dialogs else None)

    def _compare_panes(self):
        from compare import CompareDialog
        if not self.pane2.isVisible():
            self.a_split.setChecked(True)
            self.flash("Откройте в левой и правой панели две папки и повторите «Сравнить папки»")
            return
        l, r = self.pane1.current_path(), self.pane2.current_path()
        if not l or not r or not os.path.isdir(l) or not os.path.isdir(r):
            self.flash("В обеих панелях должны быть открыты обычные папки")
            return
        if os.path.normcase(l) == os.path.normcase(r):
            self.flash("В панелях открыта одна и та же папка — откройте разные")
            return
        dlg = CompareDialog(self, l, r)
        dlg.show()
        self._dialogs = getattr(self, "_dialogs", [])
        self._dialogs.append(dlg)
        dlg.finished.connect(lambda *_: self._dialogs.remove(dlg) if dlg in self._dialogs else None)

    def _open_terminal(self):
        import shellops as sh
        p = self.active_folder().path or os.path.expanduser("~")
        try:
            sh.open_terminal(p)
        except OSError as e:
            self.flash(f"Не удалось открыть терминал: {e}")

    def _last_tab_closed(self, pane):
        if pane is self.pane2:
            self.a_split.setChecked(False)
        else:
            pane.current_folder().navigate(os.path.expanduser("~"))

    def _to_other(self, copy):
        f = self.active_folder()
        other = self.other_path(f)
        sel = f.selected_paths()
        if other and sel:
            self.ops.transfer(sel, other, copy)
        elif not other:
            self.flash("Включите вторую панель (F3)")

    def _sidebar_open(self, path):
        f = self.active_folder()
        f.navigate(path)
        f.focus_view()

    def _sidebar_drop(self, urls, target, ctrl, shift):
        copy = self.ops.default_copy(urls, target, ctrl, shift)
        self.ops.transfer(urls, target, copy)

    def _set_theme(self, name):
        if name not in ("dark", "light"):
            name = "dark"
        self.settings["theme"] = name
        theme.apply(QApplication.instance(), name)
        self._apply_window_fx()
        self.sidebar.build()
        self.update()

    def _apply_window_fx(self):
        """Тёмный или светлый заголовок окна по теме."""
        if not self.isVisible() and not self.testAttribute(Qt.WA_WState_Created):
            return
        winfx.set_dark_titlebar(int(self.winId()), theme.current_name() == "dark")

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_window_fx()

    def _zoom_slider(self, v):
        f = self.active_folder()
        if f is not None and f.icon_size != v:
            f.set_icon_size(v)

    def _update_zoom(self):
        f = self.active_folder()
        if f is None:
            return
        self.zoom.setEnabled(f.mode == "icons")
        self.zoom.blockSignals(True)
        self.zoom.setValue(f.icon_size)
        self.zoom.blockSignals(False)

    # ---------- реакции на события вкладок ----------
    def _focus_changed(self, old, new):
        w = new
        while w is not None:
            if w is self.pane1 or w is self.pane2:
                if self._active is not w:
                    self._active = w
                    self._refresh_all()
                return
            w = w.parentWidget()

    def _is_active(self, f):
        return f is not None and f is self.active_folder()

    def _folder_path_changed(self, f):
        if self._is_active(f):
            if self.quicklook is not None:
                self.quicklook.hide_it()
            self._refresh_all()

    def _folder_selection_changed(self, f):
        if self._is_active(f):
            if self.quicklook is not None and self.quicklook.isVisible():
                sel = f.selected_paths()
                if sel:
                    self.quicklook.show_for(os.path.normpath(sel[0]))
                else:
                    self.quicklook.hide_it()
            self._update_preview()
            self.lbl_status.setText(f.status_text())

    def _folder_status_changed(self, f):
        if self._is_active(f):
            self.lbl_status.setText(f.status_text())

    def _refresh_all(self):
        f = self.active_folder()
        if f is None:
            return
        name = f.title()
        self.setWindowTitle(f"{name} — Orca")
        self.sidebar.set_current(f.path)
        self.lbl_status.setText(f.status_text())
        self._update_zoom()
        if f.mode in self.act_mode:
            self.act_mode[f.mode].setChecked(True)
        self._update_disk(f.path)
        self._update_preview()

    def _update_disk(self, path):
        if not path:
            self.lbl_disk.setText("")
            return
        v = QStorageInfo(path)
        if v.isValid() and v.bytesTotal() > 0:
            self.lbl_disk.setText(f"Свободно {fmt_size(v.bytesAvailable())} из {fmt_size(v.bytesTotal())}   ")
        else:
            self.lbl_disk.setText("")

    def _update_preview(self):
        if not self.preview.isVisible():
            return
        f = self.active_folder()
        if f is not None:
            self.preview.show_paths(f.selected_paths(), f.path)

    # ---------- справка ----------
    def _settings(self, tab=0):
        from settingsdlg import SettingsDialog
        SettingsDialog(self, tab if isinstance(tab, int) else 0).exec()

    def _show_keys(self):
        """Окно «Горячие клавиши» = вкладка настроек, где их можно сразу переназначить."""
        self._settings(1)

    def _about(self):
        from about import AboutDialog
        AboutDialog(self).exec()

    def _whatsnew(self, only_latest=False):
        from about import ChangelogDialog
        ChangelogDialog(self, only_latest).exec()

    def maybe_show_whatsnew(self):
        """После обновления один раз показать, что нового (при самом первом запуске тоже)."""
        import version
        if self.secondary or self.settings.get("seen_version") == version.VERSION:
            return
        self.settings["seen_version"] = version.VERSION
        from about import ChangelogDialog
        dlg = ChangelogDialog(self, only_latest=True)
        dlg.setWindowTitle(f"Orca обновлена до {version.VERSION}")
        dlg.show()
        self._whatsnew_dlg = dlg

    # ---------- закрытие ----------
    def closeEvent(self, e):
        if self.ops.busy():
            r = QMessageBox.question(self, "Orca",
                                     "Ещё идёт копирование или перенос файлов. Закрыть окно всё равно?")
            if r != QMessageBox.Yes:
                e.ignore()
                return
        from searchpanel import stop_all
        self.file_index.stop()
        stop_all()
        for pane in (self.pane1, self.pane2):
            for f in pane.folders():
                f.model.shutdown()
        s = self.settings
        s["geometry"] = bytes(self.saveGeometry().toHex()).decode()
        s["tabs1"] = [f.path for f in self.pane1.folders()]
        s["tabs2"] = [f.path for f in self.pane2.folders()]
        s["split"] = self.pane2.isVisible()
        s["show_preview"] = self.preview.isVisible()
        s["show_sidebar"] = self.sidebar.isVisible()
        s["show_hidden"] = self.show_hidden
        s["sizes_main"] = self.main.sizes()
        s["bookmarks"] = list(self.sidebar.bookmarks)
        if not self.secondary:
            cfg.save(s)
        super().closeEvent(e)
