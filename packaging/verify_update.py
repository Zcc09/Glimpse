"""Post-publish verification: the shipped exe's own update check must find the release.

    .venv/Scripts/python.exe packaging/verify_update.py

Runs the frozen build twice: as itself (must report "up to date") and pretending to be
0.1.0 (must report v0.2.0 available, with the Setup asset named).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "Glimpse" / "Glimpse.exe"
PKG_VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "glimpse" / "__init__.py").read_text(encoding="utf-8")).group(1)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)


def run_check(env_extra: dict) -> dict:
    home = Path(tempfile.mkdtemp(prefix="glimpse-updchk-"))
    env = os.environ.copy()
    env["GLIMPSE_HOME"] = str(home)
    env.update(env_extra)
    r = subprocess.run(
        [str(EXE), "--check-updates", "--json"],
        capture_output=True, timeout=180, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    # a GUI-subsystem exe still inherits the stdout pipe, so the JSON comes back here
    text = (r.stdout or b"").decode("utf-8", "replace").strip()
    data = None
    start = text.find("{")
    if start >= 0:
        try:
            data = json.loads(text[start:])
        except Exception:
            data = None
    return {"rc": r.returncode, "data": data, "stdout": text[:400]}


def main() -> int:
    if not EXE.is_file():
        print(f"missing {EXE} — build first")
        return 2

    here = run_check({})
    check("frozen exe --check-updates runs", here["rc"] == 0, f"rc={here['rc']} out={here['stdout'][:200]}")
    data = here["data"] or {}
    check("reports the configured repo", data.get("repo") == "Zcc09/Glimpse", str(data.get("repo")))
    check(f"running version is {PKG_VERSION}", data.get("current") == PKG_VERSION, str(data.get("current")))
    check(f"no update needed for {PKG_VERSION}", data.get("update_available") is False and not data.get("error"),
          f"available={data.get('update_available')} error={data.get('error')}")

    older = ".".join(["0"] + PKG_VERSION.split(".")[1:])  # same length, lower major
    old = run_check({"GLIMPSE_VERSION_OVERRIDE": older})
    odata = old["data"] or {}
    check(f"{older} sees the update", odata.get("update_available") is True, json.dumps(odata.get("latest"))[:200])
    latest = odata.get("latest") or {}
    check(f"latest tag is v{PKG_VERSION}", latest.get("tag") == f"v{PKG_VERSION}", str(latest.get("tag")))
    check("release page link present", str(latest.get("page_url", "")).startswith("https://github.com/Zcc09/Glimpse/releases/"),
          str(latest.get("page_url")))
    check("Setup asset listed", any(str(a).lower().endswith(".exe") for a in (latest.get("assets") or [])),
          str(latest.get("assets")))

    passed = sum(1 for _n, ok, _d in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
