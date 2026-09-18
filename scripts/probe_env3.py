"""Probe 3: find working translation routes from this machine."""
import json
import time

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def p(*a):
    print(*a, flush=True)


def try_route(name, fn):
    try:
        t0 = time.time()
        out = fn()
        p(f"OK   {name} ({time.time()-t0:.1f}s): {out!r}")
        return True
    except Exception as e:
        p(f"FAIL {name}: {type(e).__name__}: {str(e)[:200]}")
        return False


TEXT = "Hello, how are you today?"


def clients5():
    r = requests.get(
        "https://clients5.google.com/translate_a/t",
        params={"client": "dict-chrome-ex", "sl": "auto", "tl": "ar", "q": TEXT},
        headers={"User-Agent": UA},
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    if isinstance(j, list) and j and isinstance(j[0], list):
        return "".join(x[0] for x in j[0])
    return j


def gtx_with_headers():
    r = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "auto", "tl": "ar", "dt": "t", "q": TEXT},
        headers={
            "User-Agent": UA,
            "Referer": "https://translate.google.com/",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://translate.google.com",
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    return "".join(seg[0] for seg in data[0] if seg and seg[0])


def translate_m():
    r = requests.get(
        "https://translate.google.com/m",
        params={"sl": "auto", "tl": "ar", "q": TEXT},
        headers={"User-Agent": UA},
        timeout=20,
    )
    r.raise_for_status()
    import re

    m = re.search(r'<div class="result-container">(.*?)</div>', r.text, re.S)
    if not m:
        raise RuntimeError(f"no result div; status={r.status_code} len={len(r.text)}")
    return m.group(1).strip()


def libre_instances():
    out = []
    for base in ("https://translate.fedilab.app", "https://libretranslate.de", "https://translate.terraprint.co"):
        try:
            r = requests.post(
                base + "/translate",
                json={"q": TEXT, "source": "auto", "target": "ar", "format": "text"},
                headers={"User-Agent": UA},
                timeout=15,
            )
            if r.status_code == 200:
                j = r.json()
                if j.get("translatedText"):
                    out.append((base, j["translatedText"]))
        except Exception as e:
            out.append((base, f"{type(e).__name__}"))
    return out


def mymemory_email():
    r = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": TEXT, "langpair": "en|ar", "de": "glimpse@example.com"},
        headers={"User-Agent": UA},
        timeout=20,
    )
    j = r.json()
    return j.get("responseData", {}).get("translatedText")


try_route("clients5 dict-chrome-ex", clients5)
try_route("gtx with headers", gtx_with_headers)
try_route("translate.google.com/m", translate_m)
try_route("mymemory with email", mymemory_email)
try_route("libretranslate instances", libre_instances)
