"""Полная сборка одним запуском:  python build_all.py
1) exe через PyInstaller (с версией в свойствах файла и журналом изменений внутри),
2) архив Orca-<версия>.zip,
3) установщик Orca-Setup-<версия>.exe (нужна Inno Setup 6).
Версия берётся из version.py."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import version  # noqa: E402

V = version.VERSION
DIST = os.environ.get("ORCA_DIST", "dist")          # куда складывать сборку (по умолчанию dist)
nums = [int(x) for x in V.split(".")] + [0] * (4 - len(V.split(".")))


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd)[:160])
    quiet = kw.pop("stdout", None) is subprocess.DEVNULL
    kw.pop("stderr", None)
    if quiet:
        r = subprocess.run(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
        if r.returncode != 0:
            print(r.stdout.decode("utf-8", "replace")[-2500:])    # при ошибке показываем хвост журнала
    else:
        r = subprocess.run(cmd, cwd=HERE, **kw)
    if r.returncode != 0:
        sys.exit(f"Ошибка: команда вернула {r.returncode}")


# 1) файл с версией для exe
vf = os.path.join(HERE, "build", "version_info.txt")
os.makedirs(os.path.dirname(vf), exist_ok=True)
with open(vf, "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(nums)}, prodvers={tuple(nums)}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Maxim'),
      StringStruct('FileDescription', 'Orca - file manager'),
      StringStruct('FileVersion', '{V}'),
      StringStruct('InternalName', 'Orca'),
      StringStruct('OriginalFilename', 'Orca.exe'),
      StringStruct('ProductName', 'Orca'),
      StringStruct('ProductVersion', '{V}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
""")

# 2) exe
excl = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "tkinter", "numpy", "PIL"]
hidden = ["winthumb", "winfx", "vfs", "dupes", "compare", "quicklook", "nativemenu", "fileindex", "about", "hashdlg",
          "version", "everything", "evresults", "renamedlg", "palette", "propsdlg", "settingsdlg"]
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", "Orca",
       "--icon", os.path.join(HERE, "icon.ico"), "--version-file", vf,
       "--add-data", f"{os.path.join(HERE, 'icon.png')};.", "--add-data", f"{os.path.join(HERE, 'CHANGELOG.md')};.",
       "--paths", HERE]
for h in hidden:
    cmd += ["--hidden-import", h]
for e in excl:
    cmd += ["--exclude-module", e]
cmd += ["--distpath", os.path.join(HERE, DIST), "--workpath", os.path.join(HERE, "build"),
        "--specpath", os.path.join(HERE, "build"), os.path.join(HERE, "app.py")]
run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# 3) архив
run([sys.executable, "-I", os.path.join(HERE, "make_zip.py")], env=dict(os.environ, ORCA_DIST=DIST))

# 4) установщик
inc = os.path.join(HERE, "installer", "version.iss")
with open(inc, "w", encoding="utf-8-sig") as f:
    f.write(f'#define AppVersion "{V}"\n#define SrcDir "..\\{DIST}\\Orca"\n')
iscc = None
for c in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
          r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"):
    if os.path.exists(c):
        iscc = c
        break
if not iscc:
    sys.exit("Inno Setup не найдена — установщик не собран (exe и zip готовы)")
run([iscc, os.path.join(HERE, "installer", "orca.iss")], stdout=subprocess.DEVNULL)

print("\nГотово, версия", V)
for n in (f"Orca-{V}.zip", f"Orca-Setup-{V}.exe"):
    p = os.path.join(HERE, n)
    print(" ", n, round(os.path.getsize(p) / 1048576, 1), "МБ" if os.path.exists(p) else "НЕТ ФАЙЛА")
