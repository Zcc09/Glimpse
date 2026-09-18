"""Walk the REAL Setup wizard through every page and assert what it did.

Not the silent CLI: this runs the wizard GUI, presses the same calls the buttons
make (Next/Install), and checks the report it writes plus the files it installed,
then uninstalls the result.

    .venv/Scripts/python.exe packaging/test_wizard.py [path\\to\\Glimpse-Setup.exe | packaging/installer.py]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "Glimpse-Setup.exe"
FROM_SOURCE = TARGET.suffix == ".py"
APP_NAME = "Glimpse"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"

EXPECTED_ORDER = ["welcome", "dest", "startmenu", "tasks", "ready", "installing", "finish"]

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
    return ok


def registry_present() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY):
            return True
    except FileNotFoundError:
        return False


def wait_folder_gone(folder: Path, timeout=40) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not folder.exists():
            return True
        time.sleep(1)
    return not folder.exists()


def main() -> int:
    if not TARGET.is_file():
        print(f"not found: {TARGET}")
        return 2

    report_path = Path(tempfile.mkdtemp(prefix="glimpse-wizard-report-")) / "wizard.json"
    cmd = ([sys.executable, str(TARGET)] if FROM_SOURCE else [str(TARGET)]) + \
          ["--selftest", "--selftest-out", str(report_path)]
    print("running:", " ".join(cmd))
    r = subprocess.run(cmd, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    if not report_path.is_file():
        check("wizard wrote a report", False, f"rc={r.returncode}")
        return 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    check("wizard wrote a report", True, f"rc={r.returncode}")
    check("no walk error", "error" not in report, report.get("error", ""))

    pages = [p["page"] for p in report.get("pages", [])]
    check("page order", pages == EXPECTED_ORDER, str(pages))
    check("footer on-screen on every page", bool(report.get("footer_ok")),
          json.dumps([p for p in report.get("pages", []) if not p["footer_ok"]])[:200])
    check("no modal dialog appeared", not report.get("modals"), str(report.get("modals"))[:200])

    install = report.get("install") or {}
    check("install reported ok", bool(install.get("ok")), str(install.get("error") or ""))
    install_dir = Path(report.get("install_dir") or "")
    exe = install_dir / f"{APP_NAME}.exe"
    check("installed exe exists", exe.is_file(), str(exe))
    check("payload complete", (install_dir / "_internal").is_dir())
    check("install.json written", (install_dir / "install.json").is_file())
    check("Add/Remove entry registered", registry_present())
    check("no shortcuts touched (self test)", not (install.get("shortcuts") or []), str(install.get("shortcuts")))

    if exe.is_file():
        r = subprocess.run([str(exe), "--version"], capture_output=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or b"").decode("utf-8", "replace").strip()
        check("installed app runs", r.returncode == 0 and APP_NAME in out, out[:60])

        subprocess.run([str(exe), "--uninstall", "--silent"], capture_output=True, timeout=120,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        check("program folder removed", wait_folder_gone(install_dir), str(install_dir))
        check("Add/Remove entry removed", not registry_present())

    shutil.rmtree(install_dir.parent, ignore_errors=True)
    shutil.rmtree(report_path.parent, ignore_errors=True)

    passed = sum(1 for _n, ok, _d in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
