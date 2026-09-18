# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Glimpse setup wizard (onefile Setup.exe). Needs the
app payload in bundle/Glimpse (see packaging/build.sh):
    .venv/Scripts/python.exe -m PyInstaller --noconfirm --clean packaging/glimpse-setup.spec
"""
import os

SPEC_DIR = os.path.abspath(SPECPATH)
ROOT = os.path.dirname(SPEC_DIR)

payload = os.path.join(ROOT, "bundle", "Glimpse")
if not os.path.isdir(payload):
    raise SystemExit(f"payload missing: {payload} (run packaging/build.sh, or copy dist/Glimpse into bundle/)")
# Guard against the classic cp trap: `cp -r dist/Glimpse bundle/Glimpse` when
# bundle/Glimpse already exists nests the payload inside itself, and the Setup.exe
# then extracts to _MEI/Glimpse/Glimpse/... and fails with "payload missing".
if not os.path.isfile(os.path.join(payload, "Glimpse.exe")):
    raise SystemExit(f"payload incomplete: {payload}\\Glimpse.exe missing (stale or partial copy)")
if os.path.isdir(os.path.join(payload, "Glimpse")):
    raise SystemExit(
        f"payload nested: {payload}\\Glimpse exists — the copy nested the payload inside "
        "itself (remove bundle/ and copy again)"
    )

a = Analysis(
    [os.path.join(SPEC_DIR, "installer.py")],
    pathex=[],
    binaries=[],
    datas=[
        (payload, "Glimpse"),
        (os.path.join(ROOT, "assets", "glimpse.ico"), "."),
        (os.path.join(ROOT, "assets", "glimpse_512.png"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Glimpse-Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(ROOT, "assets", "glimpse.ico")],
    version=os.path.join(SPEC_DIR, "version_info.txt"),
)
