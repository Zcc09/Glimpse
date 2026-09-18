# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Glimpse app (onedir). Build from the repo root:
    .venv/Scripts/python.exe -m PyInstaller --noconfirm --clean packaging/glimpse.spec
"""
import os

from PyInstaller.utils.hooks import collect_all

SPEC_DIR = os.path.abspath(SPECPATH)          # packaging/
ROOT = os.path.dirname(SPEC_DIR)              # repo root

datas = [
    (os.path.join(ROOT, "assets", "glimpse.ico"), "assets"),
    (os.path.join(ROOT, "assets", "test_qr.png"), "assets"),
]
binaries = []
hiddenimports = ["glimpse.app", "glimpse.cli", "glimpse.overlay", "glimpse.ui.theme"]

# pywinrt (winsdk) and the audio/QR wheels ship modules and DLLs that the
# import analysis cannot see through, so collect them whole.
for pkg in ("winsdk", "pyaudiowpatch", "zxingcpp", "shazamio", "deep_translator"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(SPEC_DIR, "glimpse_launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pandas", "pytest"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Glimpse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(ROOT, "assets", "glimpse.ico")],
    version=os.path.join(SPEC_DIR, "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Glimpse",
)
