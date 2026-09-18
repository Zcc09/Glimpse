"""Update checker tests: version maths, asset picking, and a real GitHub check."""
from __future__ import annotations

import pytest

from .helpers import ROOT  # noqa: F401  (sys.path side effect)

from glimpse import update


# ------------------------------------------------------------------ version maths
@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("v0.2.0", "0.1.0", True),
        ("0.2.0", "0.2.0", False),
        ("v0.1.0", "0.2.0", False),
        ("v0.10.0", "0.9.9", True),
        ("v1.0", "0.99.99", True),
        ("v2.0.1", "2.0", True),
        ("2026.09.18", "0.2.0", True),
    ],
)
def test_version_comparison(latest, current, expected):
    assert update.is_newer(latest, current) is expected


def test_parse_version():
    assert update.parse_version("v1.2.3") == (1, 2, 3)
    assert update.parse_version("") == (0,)
    assert update.parse_version("v1.2.3-beta.4") == (1, 2, 3, 4)


def test_current_version_override(monkeypatch):
    real = update.current_version()
    assert real == __import__("glimpse").__version__
    monkeypatch.setenv("GLIMPSE_VERSION_OVERRIDE", "0.0.9")
    assert update.current_version() == "0.0.9"


# ------------------------------------------------------------------ assets
def test_installer_asset_preference():
    info = update.UpdateInfo(
        tag="v1.0.0",
        version="1.0.0",
        assets=[
            update.Asset("Glimpse-1.0.0-portable.zip", "https://example.com/p.zip", 10),
            update.Asset("Glimpse-Setup.exe", "https://example.com/s.exe", 20),
        ],
    )
    assert info.installer_asset().name == "Glimpse-Setup.exe"

    only_zip = update.UpdateInfo(tag="v1.0.0", version="1.0.0",
                                 assets=[update.Asset("Glimpse-1.0.0-portable.zip", "https://example.com/p.zip", 10)])
    assert only_zip.installer_asset() is None

    exe_only = update.UpdateInfo(tag="v1.0.0", version="1.0.0",
                                 assets=[update.Asset("Something.exe", "https://example.com/x.exe", 10)])
    assert exe_only.installer_asset().name == "Something.exe"


def test_is_installed_false_when_not_frozen():
    assert update.is_installed() is False


# ------------------------------------------------------------------ network
@pytest.mark.network
def test_check_for_update_against_real_repo():
    """Live check against the published repository."""
    repo = update.DEFAULT_REPO
    # pretend to be an old build: the published release must be reported as newer
    info = update.check_for_update(repo, current="0.0.1")
    assert info is not None, f"no releases found on {repo}"
    assert update.parse_version(info.tag) >= (0, 2, 0), info.tag
    assert info.page_url.startswith("https://github.com/")
    names = [a.name for a in info.assets]
    assert any(n.lower().endswith(".exe") for n in names), names

    # and pretending to be a much newer build must report "up to date"
    assert update.check_for_update(repo, current="99.99.99") is None


@pytest.mark.network
def test_check_for_update_missing_repo_raises():
    with pytest.raises(update.UpdateError):
        update.check_for_update("Zcc09/definitely-not-a-real-repo-glimpse-test", current="0.0.1")
