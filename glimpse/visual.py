"""Visual search — reverse image search through Google Lens (default) or Yandex."""
from __future__ import annotations

import json
import re
import time
from typing import Optional

import requests

from .log import log

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_session: Optional[requests.Session] = None

ENGINE_LABELS = {"google": "Google Lens", "yandex": "Yandex Images"}


class VisualSearchError(RuntimeError):
    pass


def _sess() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": UA})
    return _session


def lens_upload(png: bytes, timeout: int = 40) -> str:
    """Upload an image to Google Lens; return the results URL."""
    url = f"https://lens.google.com/v3/upload?stcs={int(time.time() * 1000)}&hl=en"
    r = _sess().post(
        url,
        files={"encoded_image": ("image.png", png, "image/png")},
        timeout=timeout,
        allow_redirects=False,
    )
    if r.status_code in (301, 302, 303, 307, 308):
        loc = r.headers.get("Location")
        if loc:
            return loc
    if r.status_code == 200:
        m = re.search(r'https://(?:lens|www)\.google\.com/[^\s"\'<>]+', r.text)
        if m:
            return m.group(0)
    raise VisualSearchError(f"Lens upload failed: HTTP {r.status_code}")


def yandex_upload(png: bytes, timeout: int = 40) -> str:
    """Upload to Yandex Images; return the cbir results URL."""
    params = {
        "rpt": "imageview",
        "format": "json",
        "request": json.dumps({"blocks": [{"block": "b-page_type_search-by-image__link"}]}),
    }
    files = {"upfile": ("blob", png, "image/png")}
    r = _sess().post("https://yandex.com/images/search", params=params, files=files, timeout=timeout)
    r.raise_for_status()
    try:
        j = r.json()
        cbir = j["blocks"][0]["params"]["cbirId"]
    except Exception as e:  # noqa: BLE001
        raise VisualSearchError(f"Yandex response unreadable: {e}") from e
    return f"https://yandex.com/images/search?rpt=imageview&cbir_id={cbir}"


def visual_search_url(png: bytes, engine: str = "google") -> str:
    engine = (engine or "google").lower()
    if engine == "yandex":
        try:
            return yandex_upload(png)
        except Exception as e:
            log.warning("yandex upload failed (%s); falling back to Google Lens", e)
    return lens_upload(png)


def text_search_url(text: str) -> str:
    from urllib.parse import quote_plus

    return "https://www.google.com/search?q=" + quote_plus(" ".join((text or "").split())[:400])


def gtranslate_url(text: str, target: str, source: str = "auto") -> str:
    from urllib.parse import quote

    return (
        f"https://translate.google.com/?sl={source or 'auto'}&tl={target}"
        f"&text={quote((text or '')[:1500])}&op=translate"
    )


def wolfram_url(text: str) -> str:
    from urllib.parse import quote_plus

    return "https://www.wolframalpha.com/input?i=" + quote_plus(text or "")
