"""Настройки: свои горячие клавиши (назначить, конфликт, вернуть, сохраняются между запусками) и параметры запуска."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
work = sys.argv[1]
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["ORCA_NO_POPUP"] = "1"

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")
import theme
theme.apply(app, "dark")
from mainwin import MainWindow
from settingsdlg import SettingsDialog

ok = True


def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and bool(cond)


def pump(ms):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


def seq(win, hid):
    return win.hotkey_actions[hid].shortcut().toString()


w = MainWindow(work)
w.resize(1100, 650)
w.move(-6000, 100)
w.show()
pump(800)
check("в реестре десятки действий", len(w.hotkey_actions) > 60)
check("есть и действия без клавиши по умолчанию (дубликаты, сравнение…)", w.hotkey_defaults.get("Найти дубликаты") == "")
check("«Новая вкладка» по умолчанию Ctrl+T", seq(w, "Новая вкладка") == "Ctrl+T")
check("повторяющиеся названия получили разные id", "Вверх" in w.hotkey_actions and "Вверх #2" in w.hotkey_actions)

# назначить свою
r = w.set_hotkey("Новая вкладка", "Ctrl+Alt+N")
check("свободное сочетание назначается", r is None and seq(w, "Новая вкладка") == "Ctrl+Alt+N")
check("подсказка кнопки обновилась", "Ctrl+Alt+N" in w.hotkey_actions["Новая вкладка"].toolTip())
check("в настройках хранится только отличие от стандартного", w.settings["hotkeys"] == {"Новая вкладка": "Ctrl+Alt+N"})

# конфликт
r = w.set_hotkey("Найти дубликаты", "Ctrl+Alt+N")
check("занятое сочетание не назначается молча (возвращён конкурент)", r == "Новая вкладка" and seq(w, "Найти дубликаты") == "")
r = w.set_hotkey("Найти дубликаты", "Ctrl+Alt+N", steal=True)
check("можно отобрать клавишу у другого действия", r is None and seq(w, "Найти дубликаты") == "Ctrl+Alt+N"
      and seq(w, "Новая вкладка") == "")
check("у «отобранного» действия клавиша убрана и это запомнено", w.settings["hotkeys"].get("Новая вкладка") == "")

# окно настроек
dlg = SettingsDialog(w, 1)
dlg.filter.setText("дубликаты")
check("фильтр в окне настроек работает", dlg.tree.topLevelItemCount() >= 1)
dlg.tree.setCurrentItem(dlg.tree.topLevelItem(0))
dlg.edit.setKeySequence(QKeySequence("Ctrl+Alt+D"))
dlg._assign()
check("назначение из окна настроек", seq(w, "Найти дубликаты") == "Ctrl+Alt+D")
dlg._default()
check("«По умолчанию» возвращает стандартную клавишу", seq(w, "Найти дубликаты") == "")
dlg._assign(clear=True)
dlg.filter.setText("")
dlg.close()

# сохраняется между запусками
w.set_hotkey("Найти дубликаты", "Ctrl+Alt+D")
w.set_hotkey("Новая вкладка", "Ctrl+T", steal=True)
w.set_hotkey("Закрыть вкладку", "Ctrl+Alt+W", steal=True)
w.close()
pump(300)
w2 = MainWindow(work)
w2.move(-6000, 100)
w2.show()
pump(500)
check("после перезапуска свои клавиши на месте", seq(w2, "Найти дубликаты") == "Ctrl+Alt+D"
      and seq(w2, "Закрыть вкладку") == "Ctrl+Alt+W" and seq(w2, "Новая вкладка") == "Ctrl+T")
w2.reset_hotkeys()
check("«Сбросить все» возвращает стандарт", seq(w2, "Закрыть вкладку") == "Ctrl+W" and seq(w2, "Найти дубликаты") == ""
      and not w2.settings["hotkeys"])

# запуск
home = os.path.expanduser("~")
w2.settings["startup"] = "home"
w2.settings["tabs1"] = [os.path.join(work, "Фото")]
w2.close()
pump(200)
w3 = MainWindow()
w3.move(-6000, 100)
w3.show()
pump(500)
check("запуск: «всегда домашняя папка»", os.path.normcase(w3.pane1.current_path()) == os.path.normcase(os.path.normpath(home)))
w3.settings["startup"] = "folder"
w3.settings["startup_path"] = os.path.join(work, "Документы")
w3.close()
pump(200)
w4 = MainWindow()
w4.move(-6000, 100)
w4.show()
pump(500)
check("запуск: «всегда эта папка»", os.path.normcase(w4.pane1.current_path()) == os.path.normcase(os.path.join(work, "Документы"))
      or os.path.normcase(w4.pane1.current_path()) == os.path.normcase(os.path.normpath(os.path.join(work, "Документы"))))
w4.settings["startup"] = "restore"
w4.close()
print("\nИТОГ:", "ВСЁ В ПОРЯДКЕ" if ok else "ЕСТЬ ОШИБКИ")
app.quit()
