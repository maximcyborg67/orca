"""Действия с файлами: копировать, вырезать, вставить, перенести, удалить, отменить."""
import os
import struct

from PySide6.QtCore import QObject, QMimeData, QUrl, Signal, QThread
from PySide6.QtGui import QGuiApplication

import shellops as sh
import vfs
from util import norm_path, drive_of, plural

DROP_EFFECT = 'application/x-qt-windows-mime;value="Preferred DropEffect"'


class _Bg(QThread):
    """Любая долгая работа (распаковать…) в фоне; результат приходит в главный поток."""
    result = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            v = self.fn()
        except Exception as e:                      # noqa: BLE001
            v = ("error", str(e))
        self.result.emit(v)


class Ops(QObject):
    message = Signal(str)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.undo_stack = []
        self._workers = []
        self._bgs = []
        self.silent = False   # для автопроверок: без окон Windows
        self.always_confirm = False   # «Всегда спрашивать перед удалением» (меню «⋯»)

    def bg(self, fn, done=None):
        t = _Bg(fn)
        self._bgs.append(t)

        def fin(v, t=t):
            if done:
                done(v)

        def cleanup(t=t):
            t.wait()           # сигнал finished приходит чуть раньше, чем поток реально остановится — дождаться
            if t in self._bgs:
                self._bgs.remove(t)
            t.deleteLater()
        t.result.connect(fin)
        t.finished.connect(cleanup)
        t.start()
        return t

    # ---------- запуск операции в фоне ----------
    def _start(self, func, srcs, dst, flags, done=None):
        if self.silent:
            flags |= sh.FOF_SILENT_NOCONFIRM
        w = sh.OpWorker(func, srcs, dst, flags, int(self.win.winId()))
        self._workers.append(w)
        w.finished.connect(lambda w=w: self._finish(w, done))
        w.start()
        return w

    def _finish(self, w, done):
        w.wait()               # иначе Qt может уничтожить ещё не остановившийся поток — это и был вылет
        if w in self._workers:
            self._workers.remove(w)
        ok = w.ok
        w.deleteLater()
        if done:
            done(ok)

    def busy(self):
        return bool(self._workers) or bool(self._bgs)

    def wait_all(self):
        """Для автопроверок."""
        from PySide6.QtWidgets import QApplication
        while self._workers or self._bgs:
            QApplication.processEvents()

    # ---------- архивы ----------
    def _materialize_then(self, paths, then):
        """Достать файлы из архива во временную папку (в фоне) и продолжить с настоящими путями."""
        n = len(paths)
        self.message.emit(f"Готовлю файлы ({n})…")

        def work():
            return vfs.materialize(paths)

        def done(v):
            if isinstance(v, tuple) and len(v) == 2 and v[0] == "error":
                self.message.emit("Не удалось: " + v[1])
                return
            real, err = v
            if err:
                self.message.emit("Не получилось получить часть файлов: " + err)
            if real:
                then(real)
        self.bg(work, done)

    def _transfer_virtual(self, srcs, dst, copy, on_done=None):
        if vfs.is_zip_path(dst):
            self.message.emit("Внутрь архива файлы класть нельзя — он открыт только для чтения")
            return
        virtual_src = [s for s in srcs if vfs.is_virtual(s)]
        if virtual_src:
            def go(real):
                real_all = real + [s for s in srcs if not vfs.is_virtual(s)]
                self.transfer(real_all, dst, True, on_done)
            self._materialize_then(srcs if len(virtual_src) == len(srcs) else virtual_src, go)

    # ---------- буфер обмена ----------
    def to_clipboard(self, paths, cut):
        if any(vfs.is_virtual(p) for p in paths):
            self._materialize_then(paths, lambda real: self.to_clipboard(real, False))
            return
        paths = [os.path.normpath(p) for p in paths]
        if not paths:
            return
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        md.setData(DROP_EFFECT, struct.pack("<I", 2 if cut else 1))
        QGuiApplication.clipboard().setMimeData(md)
        n = len(paths)
        self.message.emit(f"{'Вырезано' if cut else 'Скопировано'}: {n} {plural(n, 'объект', 'объекта', 'объектов')}")

    def clipboard_paths(self):
        md = QGuiApplication.clipboard().mimeData()
        if md is None or not md.hasUrls():
            return [], False
        paths = [os.path.normpath(u.toLocalFile()) for u in md.urls() if u.isLocalFile()]
        cut = False
        if md.hasFormat(DROP_EFFECT):
            raw = bytes(md.data(DROP_EFFECT))
            if len(raw) >= 4:
                cut = struct.unpack("<I", raw[:4])[0] == 2
        return paths, cut

    def can_paste(self):
        paths, _ = self.clipboard_paths()
        return bool(paths)

    def paste(self, dst):
        paths, cut = self.clipboard_paths()
        if not paths or not dst:
            return
        self.transfer(paths, dst, copy=not cut, on_done=(lambda ok: QGuiApplication.clipboard().clear()) if cut else None)

    # ---------- перенос / копирование ----------
    def default_copy(self, srcs, dst, ctrl=False, shift=False):
        """Как в Проводнике: между дисками копируем, на одном диске переносим; Ctrl — копия, Shift — перенос."""
        if ctrl:
            return True
        if shift:
            return False
        return any(drive_of(s) != drive_of(dst) for s in srcs)

    def transfer(self, srcs, dst, copy, on_done=None):
        if vfs.is_virtual(dst) or any(vfs.is_virtual(s) for s in srcs):
            self._transfer_virtual(srcs, dst, copy, on_done)
            return
        dst = norm_path(dst)
        items = []
        for s in srcs:
            s = norm_path(s)
            if not os.path.exists(s):
                continue
            if dst.lower() == s.lower() or dst.lower().startswith(s.lower().rstrip("\\") + "\\"):
                self.message.emit("Нельзя поместить папку саму в себя")
                continue
            if not copy and os.path.dirname(s).lower() == dst.rstrip("\\").lower():
                continue          # перенос в ту же папку — ничего не делаем
            items.append(s)
        if not items:
            return
        same_dir = copy and all(os.path.dirname(s).lower() == dst.rstrip("\\").lower() for s in items)
        pre = {s: os.path.exists(os.path.join(dst, os.path.basename(s))) for s in items}
        flags = sh.FOF_ALLOWUNDO | (sh.FOF_RENAMEONCOLLISION if same_dir else 0)
        n = len(items)
        word = plural(n, "объект", "объекта", "объектов")

        def done(ok):
            if not ok:
                self.message.emit("Операция отменена или выполнена не полностью")
            else:
                created = []
                for s in items:
                    t = os.path.join(dst, os.path.basename(s))
                    if not pre[s] and os.path.exists(t) and (copy or not os.path.exists(s)):
                        created.append((t, s))
                if created and not same_dir:
                    self._push_transfer(created, copy)
                self.message.emit(f"{'Скопировано' if copy else 'Перенесено'}: {n} {word}")
            if on_done:
                on_done(ok)

        self.message.emit(f"{'Копирую' if copy else 'Переношу'}: {n} {word}…")
        self._start(sh.FO_COPY if copy else sh.FO_MOVE, items, dst, flags, done)

    def _push_transfer(self, created, copy):
        if copy:
            targets = [t for t, _ in created]

            def undo_copy():
                if self._confirm(f"Отменить копирование? Скопированные объекты ({len(targets)}) будут перемещены в корзину."):
                    self._log("undo-copy->trash", targets)
                    self._trash(targets)
            self.push_undo("копирование", undo_copy)
        else:
            def back():
                groups = {}
                for t, s in created:
                    if os.path.exists(t) and not os.path.exists(s):
                        groups.setdefault(os.path.dirname(s), []).append(t)
                for folder, files in groups.items():
                    self._start(sh.FO_MOVE, files, folder, sh.FOF_ALLOWUNDO)
            self.push_undo("перенос", back)

    # ---------- удаление ----------
    def delete(self, paths, permanent=False, confirm=True):
        if any(vfs.is_virtual(p) for p in paths):
            self._delete_virtual(paths)
            return
        paths = [norm_path(p) for p in paths if os.path.exists(p)]
        if not paths:
            return
        n = len(paths)
        word = plural(n, "объект", "объекта", "объектов")
        dirs = [p for p in paths if os.path.isdir(p)]
        if confirm and (n >= 5 or dirs or self.always_confirm) and not self._confirm(
                f"{'Удалить НАВСЕГДА' if permanent else 'Переместить в корзину'}: {n} {word}"
                + (f", из них папок: {len(dirs)} (вместе со всем содержимым)" if dirs else "") + "?"):
            return
        self._log("delete-permanent" if permanent else "delete-trash", paths)

        def done(ok):
            self.message.emit(("Удалено навсегда" if permanent else "Перемещено в корзину")
                              + f": {n} {word}" if ok else "Удаление отменено")

        self._start(sh.FO_DELETE, paths, None, 0 if permanent else sh.FOF_ALLOWUNDO, done)

    def _delete_virtual(self, paths):
        self.message.emit("Внутри архива удалять нельзя — он открыт только для чтения")

    def _trash(self, paths):
        paths = [p for p in paths if os.path.exists(p)]
        if paths:
            self._start(sh.FO_DELETE, paths, None, sh.FOF_ALLOWUNDO)

    # ---------- подтверждение и журнал ----------
    def _confirm(self, text):
        if self.silent:
            return True
        from PySide6.QtWidgets import QMessageBox
        return QMessageBox.question(self.win, "Orca", text) == QMessageBox.Yes

    def _log(self, what, paths):
        """Журнал действий: %APPDATA%\\Provodnik\\actions.log — если что-то пропало, видно, что делала программа."""
        try:
            import settings, time
            os.makedirs(settings.DIR, exist_ok=True)
            f = os.path.join(settings.DIR, "actions.log")
            if os.path.exists(f) and os.path.getsize(f) > 1_000_000:
                os.replace(f, f + ".old")
            with open(f, "a", encoding="utf-8") as fh:
                shown = list(paths)[:40]
                more = f" (+ещё {len(paths) - 40})" if len(paths) > 40 else ""
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {what} n={len(paths)}: " + " | ".join(shown) + more + "\n")
        except Exception:
            pass

    # ---------- отмена ----------
    def push_undo(self, title, fn):
        self.undo_stack.append((title, fn))
        del self.undo_stack[:-30]

    def on_renamed(self, old, new):
        def back():
            if os.path.exists(new) and not os.path.exists(old):
                try:
                    os.rename(new, old)
                except OSError:
                    self.message.emit("Не удалось отменить переименование")
        self.push_undo("переименование", back)

    def on_created_folder(self, path):
        def back():
            try:
                os.rmdir(path)          # только пустую; если внутри что-то есть — не трогаем
            except OSError:
                self.message.emit("Папка не пуста — отмена создания пропущена, ваши файлы не тронуты")
        self.push_undo("создание папки", back)

    def undo(self):
        if not self.undo_stack:
            self.message.emit("Отменять нечего")
            return
        title, fn = self.undo_stack.pop()
        fn()
        self.message.emit(f"Отменено: {title}")
