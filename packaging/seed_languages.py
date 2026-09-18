"""Download the languages a fresh Glimpse should have on hand (offline OCR).

Bundled with the installer: eng + osd. This seeds the user's tessdata folder with
the common scripts so translation/OCR works immediately after install.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEED = [
    "ara",      # Arabic
    "urd",      # Urdu
    "fas",      # Persian
    "rus",      # Russian
    "fra",      # French
    "deu",      # German
    "spa",      # Spanish
    "ita",      # Italian
    "por",      # Portuguese
    "nld",      # Dutch
    "tur",      # Turkish
    "heb",      # Hebrew
    "hin",      # Hindi
    "ben",      # Bengali
    "chi_sim",  # Chinese (simplified)
    "chi_tra",  # Chinese (traditional)
    "jpn",      # Japanese
    "kor",      # Korean
    "tha",      # Thai
    "vie",      # Vietnamese
    "ind",      # Indonesian
    "ukr",      # Ukrainian
    "ell",      # Greek
    "pol",      # Polish
]


def main() -> int:
    from glimpse.ocr import languages as L

    target = L.tessdata_dir()
    print(f"tessdata: {target}", flush=True)
    L.ensure_bundled()

    have = set(L.installed_languages())
    todo = [c for c in SEED if c not in have]
    print(f"{len(have)} installed, {len(todo)} to fetch: {' '.join(todo) or '—'}", flush=True)

    failed: list[str] = []
    for code in todo:
        try:
            path = L.download_language(code)
            print(f"  ok {code} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)
        except Exception as e:  # noqa: BLE001
            failed.append(code)
            print(f"  FAIL {code}: {type(e).__name__}: {e}", flush=True)

    total = sum(p.stat().st_size for p in target.glob("*.traineddata")) / 1e6
    print(f"\nnow installed: {', '.join(L.installed_languages())}", flush=True)
    print(f"total {total:.1f} MB" + (f"; failed: {failed}" if failed else ""), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
