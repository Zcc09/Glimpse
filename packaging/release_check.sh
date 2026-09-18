#!/usr/bin/env bash
# Full release check: assets -> app build -> deployment test (dev) -> Setup.exe -> deployment test (Setup).
# Every step is a real run; the deployment tests install into a temp folder and uninstall again.
set -uo pipefail
cd "$(dirname "$0")/.."

PY=".venv/Scripts/python.exe"
FAIL=0
step() { echo; echo "== $* =="; }

step "assets"
"$PY" scripts/make_assets.py | tail -2 || FAIL=1

step "app build (PyInstaller onedir)"
"$PY" -m PyInstaller --noconfirm --clean packaging/glimpse.spec --distpath dist --workpath build > build/app_build.log 2>&1 \
  && echo "app built: $(du -sh dist/Glimpse | cut -f1)" || { echo "APP BUILD FAILED (see build/app_build.log)"; tail -20 build/app_build.log; exit 1; }

step "frozen app: full selftest (network + audio)"
rm -rf "$LOCALAPPDATA/Temp/glimpse-rel" && mkdir -p "$LOCALAPPDATA/Temp/glimpse-rel"
GLIMPSE_HOME="$LOCALAPPDATA/Temp/glimpse-rel" ./dist/Glimpse/Glimpse.exe --selftest --audio-test \
  --selftest-out "$LOCALAPPDATA/Temp/glimpse-rel/rep.json" \
  && echo "frozen selftest OK" || { echo "FROZEN SELFTEST FAILED"; FAIL=1; }

step "deployment test (wizard from source)"
"$PY" packaging/install_test.py packaging/installer.py || FAIL=1

step "wizard walk test (from source)"
"$PY" packaging/test_wizard.py packaging/installer.py || FAIL=1

step "bundle + Setup.exe"
rm -rf bundle && mkdir -p bundle && cp -r dist/Glimpse bundle/Glimpse
"$PY" -m PyInstaller --noconfirm --clean packaging/glimpse-setup.spec --distpath dist --workpath build > build/setup_build.log 2>&1 \
  && echo "setup built: $(ls -la dist/Glimpse-Setup.exe | awk '{print $5}') bytes" || { echo "SETUP BUILD FAILED (see build/setup_build.log)"; tail -20 build/setup_build.log; exit 1; }

step "deployment test (frozen Setup.exe)"
"$PY" packaging/install_test.py || FAIL=1

step "wizard walk test (frozen Setup.exe)"
"$PY" packaging/test_wizard.py || FAIL=1

echo
if [ "$FAIL" -eq 0 ]; then echo "RELEASE CHECK: ALL PASSED"; else echo "RELEASE CHECK: FAILURES ABOVE"; fi
exit "$FAIL"
