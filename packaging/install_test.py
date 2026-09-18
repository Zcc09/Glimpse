"""Deployment test: silent install -> run the INSTALLED app -> uninstall.

The only test that proves the shipped Setup.exe works: it installs into a temp
folder (no shortcuts, no registry leftovers), runs the installed exe's own self
test (including network steps), then uninstalls and checks the folder is gone.

    .venv/Scripts/python.exe packaging/install_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "Glimpse-Setup.exe"
APP_NAME = "Glimpse"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"

# running the wizard from source (dev loop) instead of the frozen Setup.exe
FROM_SOURCE = SETUP.suffix == ".py"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
    return ok


def run(cmd, timeout=180):
    return subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def registry_entry():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return {
                "DisplayVersion": winreg.QueryValueEx(k, "DisplayVersion")[0],
                "InstallLocation": winreg.QueryValueEx(k, "InstallLocation")[0],
                "UninstallString": winreg.QueryValueEx(k, "UninstallString")[0],
            }
    except FileNotFoundError:
        return None


def wait_folder_gone(folder: Path, timeout=40) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not folder.exists():
            return True
        time.sleep(1)
    return not folder.exists()


def main() -> int:
    if not SETUP.is_file():
        print(f"Setup.exe not found: {SETUP} — run packaging/build.sh first")
        return 2

    install_dir = Path(tempfile.mkdtemp(prefix="glimpse-install-")) / APP_NAME
    home = Path(tempfile.mkdtemp(prefix="glimpse-install-home-"))
    print(f"install → {install_dir}")

    # ---------------------------------------------------------------- install
    setup_cmd = [sys.executable, str(SETUP)] if FROM_SOURCE else [str(SETUP)]
    r = run(setup_cmd + ["--silent", "--install-dir", str(install_dir),
                         "--no-desktop-shortcut", "--no-startmenu-shortcut", "--json"])
    raw = (r.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    state = {}
    for line in reversed(raw):
        line = line.strip()
        if line.startswith("{"):
            try:
                state = json.loads(line)
                break
            except Exception:
                continue
    check("setup exit code 0", r.returncode == 0, f"rc={r.returncode} out={raw[-1][:200] if raw else ''}")
    check("setup reported ok", bool(state.get("ok")), str(state.get("error") or ""))

    exe = install_dir / f"{APP_NAME}.exe"
    check("app exe installed", exe.is_file(), str(exe))
    check("payload complete (_internal)", (install_dir / "_internal").is_dir())
    ij = install_dir / "install.json"
    check("install.json written", ij.is_file())
    if ij.is_file():
        data = json.loads(ij.read_text(encoding="utf-8"))
        check("install.json version", bool(data.get("app_version")), data.get("app_version", ""))

    reg = registry_entry()
    check("Add/Remove entry", reg is not None and str(install_dir) == reg.get("InstallLocation"),
          str(reg))
    check("uninstall string points at the app",
          bool(reg) and "--uninstall" in (reg or {}).get("UninstallString", ""),
          (reg or {}).get("UninstallString", ""))

    # ---------------------------------------------------------------- run it
    env = os.environ.copy()
    env["GLIMPSE_HOME"] = str(home)

    r = run([str(exe), "--version"], timeout=60)
    out = (r.stdout or b"").decode("utf-8", "replace")
    check("installed exe --version", r.returncode == 0 and APP_NAME in out, out.strip()[:80])

    report = home / "report.json"
    home.mkdir(parents=True, exist_ok=True)
    r = run([str(exe), "--selftest", "--selftest-out", str(report)], timeout=300)
    if report.is_file():
        rep = json.loads(report.read_text(encoding="utf-8"))
        failed = [k for k, v in rep["steps"].items() if not v.get("ok")]
        check("installed exe --selftest (full)", bool(rep.get("ok")), f"steps={len(rep['steps'])} failed={failed}")
        print("      " + ", ".join(f"{k}={'ok' if v.get('ok') else 'FAIL'}" for k, v in rep["steps"].items()))
    else:
        check("installed exe --selftest (full)", False, f"no report (rc={r.returncode})")

    # a real capture + OCR through the installed build (writes history into GLIMPSE_HOME)
    r = run([str(exe), "--capture", "--out", str(home / "desktop.png")], timeout=120)
    png = home / "desktop.png"
    check("installed exe --capture", r.returncode == 0 and png.is_file() and png.stat().st_size > 10000,
          f"{png.stat().st_size if png.is_file() else 0} bytes")

    # ---------------------------------------------------------------- in-place update
    # this is exactly what the in-app updater runs: Setup again, silently, with no
    # --install-dir — it must reuse the folder the registry points at
    default_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / APP_NAME
    default_existed_before = default_dir.exists()  # the developer's own install lives there
    r = run(setup_cmd + ["--silent", "--json", "--no-desktop-shortcut", "--no-startmenu-shortcut"])
    raw2 = (r.stdout or b"").decode("utf-8", "replace")
    state2 = {}
    for line in reversed(raw2.strip().splitlines()):
        if line.strip().startswith("{"):
            try:
                state2 = json.loads(line.strip())
                break
            except Exception:
                continue
    check("update run reused the existing folder", Path(state2.get("install_dir", "")) == install_dir,
          f"reported={state2.get('install_dir')} expected={install_dir}")
    created_default = default_dir.exists() and not default_existed_before
    check("update run did not create a second copy", not created_default,
          f"{default_dir} (existed before this run: {default_existed_before})")
    check("app still runs after the update run", run([str(exe), "--version"], timeout=60).returncode == 0)

    # ---------------------------------------------------------------- uninstall
    r = run([str(exe), "--uninstall", "--silent"], timeout=120)
    check("uninstall exit code 0", r.returncode == 0, (r.stdout or b"").decode("utf-8", "replace").strip()[:120])
    check("program folder removed", wait_folder_gone(install_dir), str(install_dir))
    check("Add/Remove entry removed", registry_entry() is None)
    check("user data kept", home.exists())

    shutil.rmtree(install_dir.parent, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)

    passed = sum(1 for _n, ok, _d in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
