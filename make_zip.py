"""Собирает архив для друга: папка программы + ПРОЧТИ.txt + журнал изменений. Запуск: python make_zip.py"""
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import version  # noqa: E402

SRC = os.path.join(HERE, os.environ.get("ORCA_DIST", "dist"), "Orca")
OUT = os.path.join(HERE, f"Orca-{version.VERSION}.zip")

if os.path.exists(OUT):
    os.remove(OUT)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    z.write(os.path.join(HERE, "ПРОЧТИ.txt"), "Orca/ПРОЧТИ.txt")
    z.write(os.path.join(HERE, "CHANGELOG.md"), "Orca/ЖУРНАЛ ИЗМЕНЕНИЙ.md")
    for root, _dirs, files in os.walk(SRC):
        for f in files:
            full = os.path.join(root, f)
            z.write(full, os.path.join("Orca", os.path.relpath(full, SRC)))
print("готово:", OUT, round(os.path.getsize(OUT) / 1048576, 1), "МБ")
