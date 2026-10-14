"""Настройки программы: лежат в %APPDATA%\\Provodnik\\settings.json."""
import json
import os

DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Provodnik")
FILE = os.path.join(DIR, "settings.json")

DEFAULTS = {
    "theme": "dark",
    "mode": "details",          # icons | compact | details
    "icon_size": 96,
    "show_hidden": False,
    "show_sidebar": True,
    "show_preview": False,
    "split": False,
    "bookmarks": [],
    "tabs1": [],
    "tabs2": [],
    "geometry": "",
    "sizes_main": [],
}


def load():
    data = dict(DEFAULTS)
    try:
        with open(FILE, "r", encoding="utf-8-sig") as f:
            data.update(json.load(f))
    except (OSError, ValueError):
        pass
    return data


def save(data):
    try:
        os.makedirs(DIR, exist_ok=True)
        tmp = FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, FILE)
    except OSError:
        pass
