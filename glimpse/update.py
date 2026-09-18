"""GitHub-release updates: check for a newer release, download it, install it.

Publishing convention this expects (same as the other Zcc09 apps):
  tag `vX.Y.Z`, assets include `Glimpse-Setup.exe` (and optionally a portable zip).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import requests

from . import __app_name__, __version__
from . import proc as proc_mod
from .log import log

GITHUB_API = "https://api.github.com"
UA = f"{__app_name__}/{__version__}"
DEFAULT_REPO = "Zcc09/Glimpse"


class UpdateError(RuntimeError):
    pass


# ------------------------------------------------------------------ versions
def current_version() -> str:
    """The running version. GLIMPSE_VERSION_OVERRIDE lets tests impersonate an
    older build without shipping a second binary."""
    return os.environ.get("GLIMPSE_VERSION_OVERRIDE") or __version__


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", (text or "").strip().lstrip("vV"))
    if not nums:
        return (0,)
    return tuple(int(n) for n in nums[:4])


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


# ------------------------------------------------------------------ data
@dataclass
class Asset:
    name: str
    url: str
    size: int = 0


@dataclass
class UpdateInfo:
    tag: str
    version: str
    title: str = ""
    notes: str = ""
    page_url: str = ""
    published_at: str = ""
    assets: list[Asset] = field(default_factory=list)

    def installer_asset(self) -> Optional[Asset]:
        exes = [a for a in self.assets if a.name.lower().endswith(".exe")]
        setups = [a for a in exes if "setup" in a.name.lower()]
        return (setups or exes or [None])[0]  # type: ignore[return-value]


def releases_page(repo: str) -> str:
    return f"https://github.com/{repo}/releases"


# ------------------------------------------------------------------ check
def check_for_update(
    repo: str = DEFAULT_REPO,
    current: str | None = None,
    timeout: int = 15,
    include_prerelease: bool = False,
) -> Optional[UpdateInfo]:
    """Return UpdateInfo when a newer release exists, else None.

    Raises UpdateError when the repository cannot be read at all.
    """
    cur = current or current_version()
    try:
        r = requests.get(
            f"{GITHUB_API}/repos/{repo}/releases",
            params={"per_page": 10},
            headers={"Accept": "application/vnd.github+json", "User-Agent": UA},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise UpdateError(f"could not reach GitHub: {e}") from e

    if r.status_code == 404:
        raise UpdateError(f"repository '{repo}' not found (or has no releases)")
    if r.status_code == 403:
        raise UpdateError("GitHub rate limit reached — try again later")
    try:
        r.raise_for_status()
        releases = r.json()
    except Exception as e:  # noqa: BLE001
        raise UpdateError(f"unexpected response from GitHub: {e}") from e
    if not isinstance(releases, list):
        raise UpdateError("unexpected response from GitHub")

    for rel in releases:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        if rel.get("prerelease") and not include_prerelease:
            continue
        tag = str(rel.get("tag_name") or "")
        if not parse_version(tag):
            continue
        if not is_newer(tag, cur):
            return None  # newest published release is not newer than what we run
        return UpdateInfo(
            tag=tag,
            version=tag.lstrip("vV"),
            title=str(rel.get("name") or tag),
            notes=str(rel.get("body") or ""),
            page_url=str(rel.get("html_url") or releases_page(repo)),
            published_at=str(rel.get("published_at") or ""),
            assets=[
                Asset(a.get("name", ""), a.get("browser_download_url", ""), int(a.get("size") or 0))
                for a in (rel.get("assets") or [])
                if isinstance(a, dict)
            ],
        )
    return None


# ------------------------------------------------------------------ download / install
def download(
    url: str,
    dest: Path,
    progress: Optional[Callable[[int, int], None]] = None,
    timeout: int = 120,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": UA}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    os.replace(tmp, dest)
    log.info("downloaded %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def is_installed() -> bool:
    """True when this exe sits in a folder our Setup created."""
    if not getattr(sys, "frozen", False):
        return False
    return (Path(sys.executable).parent / "install.json").is_file()


def launch_installer(path: Path, silent: bool = True, launch_after: bool = True) -> bool:
    """Run the downloaded Setup.exe detached (it can then replace our files)."""
    args = [str(path)]
    if silent:
        args.append("--silent")
    if launch_after:
        args.append("--launch")
    flags = proc_mod.DETACHED_PROCESS | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        proc_mod.popen(args, cwd=str(Path(path).parent), creationflags=flags, close_fds=True)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("could not launch installer: %s", e)
        return False


def download_dir() -> Path:
    d = Path.home() / "Downloads"
    return d if d.is_dir() else Path.home()
