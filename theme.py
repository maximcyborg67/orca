"""Цвета и оформление: тёмная, светлая и «стеклянные» темы (прозрачность настраивается)."""
from PySide6.QtGui import QColor, QPalette

THEMES = {
    "dark": dict(bg="#1b1c1f", panel="#222428", base="#26282c", alt="#2d2f35", text="#e8e9ec",
                 dim="#9a9ea8", border="#383b42", accent="#5b9dff", hover="#30333a", sel="#2f4468",
                 sel_dim="#33363d"),
    "light": dict(bg="#eef0f3", panel="#f7f8fa", base="#ffffff", alt="#f1f3f6", text="#1f2328",
                  dim="#6b7280", border="#d5d9df", accent="#2f6fe0", hover="#e6e9ee", sel="#cfe0ff",
                  sel_dim="#e3e6eb"),
}
GLASS = ()          # тема «Стекло» убрана по просьбе пользователя; код make_glass оставлен неиспользуемым
GLASS_NAMES = {}
DEFAULT_ALPHA = 0.6

_current = dict(THEMES["dark"])
_name = "dark"
_alpha = DEFAULT_ALPHA


def is_glass(name=None):
    return (name or _name) in GLASS


def rgba(r, g, b, a):
    return f"rgba({r}, {g}, {b}, {max(0, min(255, int(round(a * 255))))})"


def make_glass(name, a):
    """Цвета «стекла»: чем меньше a, тем прозрачнее. Слои накладываются друг на друга, поэтому у каждого свой коэффициент."""
    # Как в Windows 11: «рамка» (боковая панель, панель инструментов, вкладки, статус) прозрачная и регулируется ползунком,
    # а сам список файлов почти плотный — текст читается на любых обоях.
    a = max(0.12, min(1.0, a))
    chrome = 0.10 + 0.88 * a                   # 12 %..100 % ползунка -> 0.2..0.98 непрозрачности рамки
    content = 0.86 + 0.12 * a                  # список файлов: всегда 0.88..0.98
    under = 0.30 * chrome                      # слой под всем (виден только в щелях)
    if name == "glass":
        tint = (18, 22, 34)
        hi = (255, 255, 255)
        return dict(bg=rgba(*tint, under), panel=rgba(*tint, chrome), base=rgba(24, 28, 40, content),
                    alt=rgba(*hi, 0.075), text="#f3f5fa", dim="#a9b0c0", border=rgba(*hi, 0.12),
                    accent="#8ab8ff", hover=rgba(*hi, 0.09), sel=rgba(120, 170, 255, 0.30),
                    sel_dim=rgba(*hi, 0.11))
    tint = (240, 244, 252)
    lo = (20, 30, 50)
    return dict(bg=rgba(*tint, under), panel=rgba(*tint, chrome), base=rgba(252, 253, 255, content),
                alt=rgba(*lo, 0.05), text="#161a22", dim="#566073", border=rgba(*lo, 0.13),
                accent="#2f6fe0", hover=rgba(*lo, 0.07), sel=rgba(47, 111, 224, 0.22),
                sel_dim=rgba(*lo, 0.09))


def qcol(spec):
    """'#rrggbb' или 'rgba(r, g, b, a)' -> QColor."""
    if isinstance(spec, str) and spec.startswith("rgba("):
        r, g, b, a = [int(x) for x in spec[5:-1].split(",")]
        return QColor(r, g, b, a)
    return QColor(spec)


def colors():
    return _current


def current_name():
    return _name


def apply(app, name, alpha=None):
    global _name, _alpha
    if alpha is not None:
        _alpha = alpha
    _name = name if (name in THEMES or name in GLASS) else "dark"
    c = make_glass(_name, _alpha) if _name in GLASS else THEMES[_name]
    _current.clear()
    _current.update(c)
    pal = QPalette()
    q = qcol
    pal.setColor(QPalette.Window, q(c["bg"]))
    pal.setColor(QPalette.WindowText, q(c["text"]))
    pal.setColor(QPalette.Base, q(c["base"]))
    pal.setColor(QPalette.AlternateBase, q(c["alt"]))
    pal.setColor(QPalette.Text, q(c["text"]))
    pal.setColor(QPalette.Button, q(c["panel"]))
    pal.setColor(QPalette.ButtonText, q(c["text"]))
    pal.setColor(QPalette.ToolTipBase, QColor("#20232b") if _name != "glass_light" else QColor("#f4f6fb"))
    pal.setColor(QPalette.ToolTipText, q(c["text"]))
    pal.setColor(QPalette.Highlight, q(c["sel"]))
    pal.setColor(QPalette.HighlightedText, q(c["text"]))
    pal.setColor(QPalette.PlaceholderText, q(c["dim"]))
    pal.setColor(QPalette.Link, q(c["accent"]))
    pal.setColor(QPalette.Mid, q(c["border"]))
    pal.setColor(QPalette.Disabled, QPalette.Text, q(c["dim"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, q(c["dim"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, q(c["dim"]))
    app.setPalette(pal)
    app.setStyleSheet(_qss(c, _name in GLASS))


def _qss(c, glass=False):
    # у «стекла» всплывающие меню и подсказки делаем плотнее, чтобы текст читался на любых обоях
    menu_bg = "rgba(24, 28, 40, 238)" if c["text"] == "#f5f7fb" else ("rgba(246, 248, 252, 240)" if glass else c["panel"])
    if not glass:
        menu_bg = c["panel"]
    tip_bg = menu_bg if glass else c["panel"]
    return f"""
QToolTip {{ background: {tip_bg}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px 6px; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QToolBar {{ background: {c['panel']}; border: none; border-bottom: 1px solid {c['border']}; padding: 4px 8px; spacing: 2px; }}
QToolBar::separator {{ width: 1px; background: {c['border']}; margin: 6px 6px; }}
QToolButton {{ border: none; border-radius: 6px; padding: 5px 8px; color: {c['text']}; background: transparent; }}
QToolButton:hover {{ background: {c['hover']}; }}
QToolButton:pressed {{ background: {c['sel_dim']}; }}
QToolButton:checked {{ background: {c['sel']}; }}
QToolButton:disabled {{ color: {c['dim']}; }}
QToolButton::menu-indicator {{ image: none; width: 0px; }}
QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {c['dim']}; padding: 6px 12px; margin: 5px 2px 0 2px;
               border-radius: 7px; min-width: 90px; max-width: 220px; }}
QTabBar::tab:selected {{ background: {c['panel']}; color: {c['text']}; }}
QTabBar::tab:hover:!selected {{ background: {c['hover']}; }}
QTabBar::close-button {{ subcontrol-position: right; border-radius: 4px; }}
QTabBar::close-button:hover {{ background: {c['border']}; }}
QTreeView, QListView {{ background: {c['base']}; border: none; outline: 0; }}
QTreeView::item {{ padding: 3px 0; border: none; }}
QTreeView::item:hover {{ background: {c['hover']}; }}
QTreeView::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QTreeView::item:selected:!active {{ background: {c['sel_dim']}; }}
QListView::item:hover {{ background: {c['hover']}; border-radius: 6px; }}
QListView::item:selected {{ background: {c['sel']}; color: {c['text']}; border-radius: 6px; }}
QListView::item:selected:!active {{ background: {c['sel_dim']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {c['dim']}; border: none; padding: 6px 8px;
                       border-bottom: 1px solid {c['border']}; }}
QHeaderView::section:hover {{ background: {c['hover']}; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 36px; margin: 2px 2px; }}
QScrollBar::handle:vertical:hover {{ background: {c['dim']}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 4px; min-width: 36px; margin: 2px 2px; }}
QScrollBar::handle:horizontal:hover {{ background: {c['dim']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QLineEdit {{ background: {c['alt']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 5px 9px;
            color: {c['text']}; selection-background-color: {c['accent']}; selection-color: #ffffff; }}
QLineEdit:focus {{ border: 1px solid {c['accent']}; }}
QStatusBar {{ background: {c['panel']}; color: {c['dim']}; border-top: 1px solid {c['border']}; }}
QStatusBar::item {{ border: none; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {c['accent']}; }}
QMenu {{ background: {menu_bg}; border: 1px solid {c['border']}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 30px 6px 14px; border-radius: 5px; color: {c['text']}; }}
QMenu::item:selected {{ background: {c['sel']}; }}
QMenu::item:disabled {{ color: {c['dim']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['text']}; width: 12px; margin: -5px 0; border-radius: 6px; }}
#crumbs {{ background: {c['alt']}; border: 1px solid {c['border']}; border-radius: 7px; }}
#crumbs QToolButton {{ padding: 3px 6px; border-radius: 5px; }}
#crumbs QToolButton[chev="true"] {{ padding: 3px 3px; color: {c['dim']}; }}
#sidebar {{ background: {c['panel']}; border: none; border-right: 1px solid {c['border']}; }}
#sidebar::item {{ border-radius: 6px; margin: 1px 6px; }}
#sidebar::item:hover {{ background: {c['hover']}; }}
#sidebar::item:selected {{ background: {c['sel']}; }}
#infopanel {{ background: {c['panel']}; border-left: 1px solid {c['border']}; }}
QPlainTextEdit {{ background: {c['base']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 4px; color: {c['text']}; }}
QLabel {{ background: transparent; }}
"""
