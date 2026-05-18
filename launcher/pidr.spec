# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for TELMA Dashboard — Windows onedir build.

Build with:
    pyinstaller launcher/pidr.spec

Run from the project root so the relative paths below resolve correctly.
"""
import os
from PyInstaller.utils.hooks import collect_all, copy_metadata

PROJECT_ROOT = os.path.abspath(os.getcwd())
LAUNCHER_DIR = os.path.join(PROJECT_ROOT, "launcher")
JRE_DIR = os.path.join(LAUNCHER_DIR, "jre")

# Streamlit ships static assets and runtime files PyInstaller can't auto-detect.
st_datas, st_binaries, st_hidden = collect_all("streamlit")
ow_datas, ow_binaries, ow_hidden = collect_all("owlready2")
pl_datas, pl_binaries, pl_hidden = collect_all("plotly")
wv_datas, wv_binaries, wv_hidden = collect_all("webview")

datas = []
datas += st_datas + ow_datas + pl_datas + wv_datas
datas += copy_metadata("streamlit")
datas += [
    (os.path.join(PROJECT_ROOT, "dashboard.py"), "."),
    (os.path.join(PROJECT_ROOT, "update_ontology.py"), "."),
    (os.path.join(PROJECT_ROOT, "data_collection.py"), "."),
    (os.path.join(PROJECT_ROOT, "ontology", "KARMA_v014.owl"), "ontology"),
]

# Optional resources — only bundle if present.
optional_pairs = [
    (os.path.join(PROJECT_ROOT, "ontology", "KARMA_v014_live.owl"), "ontology"),
    (os.path.join(PROJECT_ROOT, "README.md"), "."),
]
for src, dst in optional_pairs:
    if os.path.exists(src):
        datas.append((src, dst))

# Bundle the entire JRE folder as data so the launcher can point JAVA_HOME at it.
if os.path.isdir(JRE_DIR):
    for root, _dirs, files in os.walk(JRE_DIR):
        rel = os.path.relpath(root, JRE_DIR)
        target = os.path.join("jre", rel) if rel != "." else "jre"
        for f in files:
            datas.append((os.path.join(root, f), target))

binaries = st_binaries + ow_binaries + pl_binaries + wv_binaries

hiddenimports = list({
    *st_hidden, *ow_hidden, *pl_hidden, *wv_hidden,
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
    "streamlit.runtime.caching",
    "pymongo",
    "opcua",
    "dateutil",
    "dateutil.parser",
    "pandas",
    "plotly",
    "plotly.graph_objects",
    "webview",
    "webview.platforms.winforms",
})

block_cipher = None


a = Analysis(
    [os.path.join(LAUNCHER_DIR, "pidr_launcher.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="telma-dashboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                     # windowed: no console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(LAUNCHER_DIR, "pidr.ico") if os.path.exists(os.path.join(LAUNCHER_DIR, "pidr.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="telma",
)
