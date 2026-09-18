"""Publish Glimpse to GitHub: repo (if needed), push, release, asset upload.

Uses the git credential already stored for github.com — the token is read via
`git credential fill` and never printed.

    .venv/Scripts/python.exe packaging/publish_release.py --version 0.2.0 \
        --notes release_notes.md [--assets dist/Glimpse-Setup.exe dist/Glimpse-0.2.0-portable.zip]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
REPO = "Zcc09/Glimpse"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def git_token() -> tuple[str, str]:
    """(username, token) from the stored git credential — never echoed."""
    out = subprocess.run(
        ["git", "credential", "fill"],
        input=b"protocol=https\nhost=github.com\n\n",
        capture_output=True,
        cwd=str(ROOT),
    )
    data = {}
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    if not data.get("password"):
        raise SystemExit("no stored GitHub credential found (git credential fill returned nothing)")
    return data.get("username", ""), data["password"]


def gh(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "Glimpse-publish"}


def ensure_repo(session: requests.Session, token: str) -> str:
    r = session.get(f"{API}/repos/{REPO}", headers=gh(token), timeout=20)
    if r.status_code == 200:
        print(f"repo exists: {r.json()['html_url']}")
        return r.json()["html_url"]
    if r.status_code != 404:
        raise SystemExit(f"unexpected repo lookup status {r.status_code}: {r.text[:200]}")
    r = session.post(
        f"{API}/user/repos",
        headers=gh(token),
        json={
            "name": REPO.split("/")[1],
            "description": "Glimpse — Google Lens for Windows: snipping-tool overlay with OCR, translate, visual search, QR and song ID.",
            "private": False,
            "has_issues": True,
            "has_wiki": False,
            "auto_init": False,
        },
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise SystemExit(f"could not create repo ({r.status_code}): {r.text[:300]}")
    print(f"repo created: {r.json()['html_url']}")
    return r.json()["html_url"]


def git(*args: str) -> None:
    r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.decode('utf-8', 'replace')}")
    out = r.stdout.decode("utf-8", "replace").strip()
    if out:
        print(out)


def portable_zip(version: str) -> Path:
    src = ROOT / "dist" / "Glimpse"
    if not (src / "Glimpse.exe").is_file():
        raise SystemExit(f"missing app build: {src}")
    out = ROOT / "dist" / f"Glimpse-{version}-portable.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                z.write(path, Path("Glimpse") / path.relative_to(src))
    print(f"portable zip: {out} ({out.stat().st_size/1e6:.0f} MB)")
    return out


def upload_asset(session: requests.Session, token: str, release: dict, path: Path) -> None:
    name = path.name
    existing = {a["name"] for a in release.get("assets", [])}
    if name in existing:
        print(f"asset already on release: {name}")
        return
    with open(path, "rb") as f:
        r = session.post(
            f"{UPLOADS}/repos/{REPO}/releases/{release['id']}/assets?name={name}",
            headers={**gh(token), "Content-Type": "application/octet-stream"},
            data=f,
            timeout=1800,
        )
    if r.status_code not in (200, 201):
        raise SystemExit(f"asset upload failed for {name} ({r.status_code}): {r.text[:300]}")
    print(f"uploaded {name}: {r.json()['browser_download_url']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="e.g. 0.2.0 (tag will be v0.2.0)")
    ap.add_argument("--notes", help="file with the release notes (markdown)")
    ap.add_argument("--assets", nargs="*", default=None, help="asset paths (default: Setup.exe + portable zip)")
    ap.add_argument("--recreate", action="store_true", help="delete an existing release with this tag first")
    args = ap.parse_args()

    tag = args.version if args.version.startswith("v") else f"v{args.version}"
    notes = Path(args.notes).read_text(encoding="utf-8") if args.notes else f"Glimpse {tag}"

    session = requests.Session()
    _user, token = git_token()

    ensure_repo(session, token)

    # push (uses the stored git credential; no token on any command line)
    remotes = subprocess.run(["git", "remote"], cwd=str(ROOT), capture_output=True).stdout.decode().split()
    if "origin" in remotes:
        git("remote", "set-url", "origin", f"https://github.com/{REPO}.git")
    else:
        git("remote", "add", "origin", f"https://github.com/{REPO}.git")
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=str(ROOT), capture_output=True).stdout.decode().strip() or "main"
    git("push", "-u", "origin", f"{branch}:main")

    assets = [Path(p) for p in (args.assets or [])]
    if not assets:
        setup = ROOT / "dist" / "Glimpse-Setup.exe"
        if not setup.is_file():
            raise SystemExit(f"missing {setup} — build first (packaging/release_check.sh)")
        assets = [setup, portable_zip(args.version)]
    for a in assets:
        if not a.is_file():
            raise SystemExit(f"missing asset: {a}")

    r = session.get(f"{API}/repos/{REPO}/releases/tags/{tag}", headers=gh(token), timeout=20)
    if r.status_code == 200:
        rel = r.json()
        if args.recreate:
            d = session.delete(f"{API}/repos/{REPO}/releases/{rel['id']}", headers=gh(token), timeout=30)
            if d.status_code != 204:
                raise SystemExit(f"could not delete existing release: {d.status_code}")
            rel = None
        else:
            print(f"release {tag} already exists — uploading any missing assets")
    else:
        rel = None

    if rel is None:
        r = session.post(
            f"{API}/repos/{REPO}/releases",
            headers=gh(token),
            json={
                "tag_name": tag,
                "target_commitish": "main",
                "name": f"Glimpse {args.version}",
                "body": notes,
                "draft": False,
                "prerelease": False,
            },
            timeout=60,
        )
        if r.status_code not in (200, 201):
            raise SystemExit(f"could not create release ({r.status_code}): {r.text[:300]}")
        rel = r.json()
        print(f"release created: {rel['html_url']}")
    else:
        # refresh asset list for uploads
        rel = session.get(f"{API}/repos/{REPO}/releases/{rel['id']}", headers=gh(token), timeout=20).json()

    for a in assets:
        upload_asset(session, token, rel, a)

    final = session.get(f"{API}/repos/{REPO}/releases/latest", headers=gh(token), timeout=20).json()
    print("\nlatest release now:")
    print(json.dumps({"tag": final["tag_name"], "assets": [x["name"] for x in final["assets"]], "url": final["html_url"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
