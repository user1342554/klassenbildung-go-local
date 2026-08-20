# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec fuer das selbststaendige Linux-Programmpaket."""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
REPO_ROOT = os.path.abspath(os.path.join(SPEC_DIR, ".."))
sys.path.insert(0, REPO_ROOT)

datas = [
    (os.path.join(REPO_ROOT, "app.py"), "."),
    (os.path.join(REPO_ROOT, "DummyDaten.xlsx"), "."),
    (os.path.join(REPO_ROOT, "config", "settings.default.json"), "config"),
    (os.path.join(REPO_ROOT, "config", "class_profiles.default.json"), "config"),
    (os.path.join(REPO_ROOT, ".streamlit", "config.toml"), ".streamlit"),
    (
        os.path.join(REPO_ROOT, "klassenbildung", "components", "assignment_board", "index.html"),
        "klassenbildung/components/assignment_board",
    ),
]
binaries = []
hiddenimports = []

for package in ("streamlit", "ortools", "pandas", "openpyxl", "altair", "pyarrow"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

hiddenimports += collect_submodules("klassenbildung")

analysis = Analysis(
    [os.path.join(SPEC_DIR, "native_launcher.py")],
    pathex=[REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Klassenbildung",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Klassenbildung",
)
