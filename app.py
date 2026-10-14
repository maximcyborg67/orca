"""Orca — запуск. Можно передать папку: python app.py D:\\Фото"""
import os
import sys

# чёткий текст и значки на экранах с масштабом 125–200 %
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


_LOG = None


def _setup_crash_log():
    """Журнал %APPDATA%\\Provodnik\\orca.log: ошибки Python, предупреждения Qt и место аварийного падения."""
    global _LOG
    import faulthandler
    import time
    import traceback
    import settings
    try:
        os.makedirs(settings.DIR, exist_ok=True)
        path = os.path.join(settings.DIR, "orca.log")
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".old")
        _LOG = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    _LOG.write(f"\n=== запуск {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    faulthandler.enable(file=_LOG, all_threads=True)

    def hook(t, v, tb):
        _LOG.write("".join(traceback.format_exception(t, v, tb)))
    sys.excepthook = hook
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType

    def qt_handler(mode, ctx, msg):
        if mode != QtMsgType.QtDebugMsg:
            _LOG.write(f"{time.strftime('%H:%M:%S')} Qt {mode.name}: {msg}\n")
    qInstallMessageHandler(qt_handler)


def main(argv=None):
    _setup_crash_log()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QGuiApplication
    from PySide6.QtWidgets import QApplication

    argv = list(sys.argv if argv is None else argv)
    try:   # свой значок в панели задач, а не значок Python
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Orca.FileManager")
    except Exception:
        pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("Orca")
    app.setStyle("Fusion")
    f = QFont("Segoe UI Variable Text", 10)
    f.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(f)

    import settings as cfg
    import theme
    st = cfg.load()
    theme.apply(app, st.get("theme", "dark"), float(st.get("glass_alpha", theme.DEFAULT_ALPHA)))

    from mainwin import MainWindow
    start = argv[1] if len(argv) > 1 and os.path.isdir(argv[1]) else None
    from PySide6.QtGui import QIcon
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    icon = os.path.join(base, "icon.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    w = MainWindow(start)
    w.show()
    if not os.environ.get("PROV_SHOT") and not os.environ.get("ORCA_NO_INDEX"):
        from PySide6.QtCore import QTimer as _T
        _T.singleShot(4000, w.file_index.refresh_if_stale)     # индекс файлов для поиска по всему ПК обновляется в фоне
    if not os.environ.get("PROV_SHOT") and not os.environ.get("ORCA_NO_POPUP"):
        from PySide6.QtCore import QTimer as _T2
        _T2.singleShot(1200, w.maybe_show_whatsnew)           # после обновления — окно «Что нового» (один раз)
    shot = os.environ.get("PROV_SHOT")      # для автопроверки: снимок окна и выход
    if shot:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2500, lambda: (w.grab().save(shot), app.quit()))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
