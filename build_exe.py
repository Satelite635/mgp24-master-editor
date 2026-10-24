"""Builds dist/MGP24MasterEditor.exe (one file, Python + pycryptodome bundled). Run on Windows:
    pip install pyinstaller pycryptodome
    python build_exe.py
(PyInstaller can't cross-compile: a Linux run builds a Linux binary, only useful as a smoke test.)"""
import glob, os, sys
import PyInstaller.__main__

os.chdir(os.path.dirname(os.path.abspath(__file__)))
mods = [os.path.splitext(f)[0] for f in glob.glob("*.py") if not f.startswith(("test_", "build_"))]
args = ["motogp_master_editor.py", "--onefile", "--console", "--noconfirm", "--clean",
        "--name", "MGP24MasterEditor", "--add-data", "webui.html" + os.pathsep + "."]
for m in mods:                       # webui imports some tools lazily; make sure all are in
    args += ["--hidden-import", m]
PyInstaller.__main__.run(args)
