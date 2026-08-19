# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec fuer das unsignierte macOS-App-Paket."""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Repo-Wurzel importierbar machen, damit das lokale Paket eingesammelt wird.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), ".."))
sys.path.insert(0, REPO_ROOT)

datas = [
    ("../app.py", "."),
    ("../config/settings.default.json", "config"),
    ("../config/class_profiles.default.json", "config"),
    ("../.streamlit/config.toml", ".streamlit"),
    ("../klassenbildung/components/assignment_board/index.html",
     "klassenbildung/components/assignment_board"),
]
binaries = []
hiddenimports = []

for package in ("streamlit", "ortools", "pandas", "openpyxl", "altair", "pyarrow"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += collect_submodules("klassenbildung")

a = Analysis(
    ["launcher.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Klassenbildung",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Klassenbildung",
)

app = BUNDLE(
    coll,
    name="Klassenbildung.app",
    icon=None,
    bundle_identifier="de.klassenbildung.local",
    info_plist={
        "CFBundleName": "Klassenbildung",
        "CFBundleDisplayName": "Klassenbildung",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "LSBackgroundOnly": False,
    },
)
