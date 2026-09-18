#!/usr/bin/env bash
# Build Glimpse: assets -> app (onedir) -> bundle -> Setup.exe
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/Scripts/python.exe"

echo "== assets =="
"$PY" scripts/make_assets.py | tail -2

echo "== app (onedir) =="
"$PY" -m PyInstaller --noconfirm --clean packaging/glimpse.spec --distpath dist --workpath build | tail -3

echo "== bundle =="
rm -rf bundle
mkdir -p bundle
cp -r dist/Glimpse bundle/Glimpse
du -sh bundle/Glimpse

echo "== setup (onefile) =="
"$PY" -m PyInstaller --noconfirm --clean packaging/glimpse-setup.spec --distpath dist --workpath build | tail -3

echo "== artifacts =="
ls -la dist/ dist/Glimpse/Glimpse.exe dist/Glimpse-Setup.exe 2>/dev/null | head -20
