"""Probe 2: translation endpoints + Yandex response shape. Run with venv python."""
import json
import sys
import time

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
S = requests.Session()
S.headers.update({"User-Agent": UA})


def p(*a):
    print(*a, flush=True)


def gtx(text, sl, tl):
    r = S.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": text},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    out = "".join(seg[0] for seg in data[0] if seg and seg[0])
    detected = data[2] if len(data) > 2 else "?"
    return out, detected


def mymemory(text, pair):
    r = S.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text, "langpair": pair},
        timeout=20,
    )
    j = r.json()
    return j.get("responseData", {}).get("translatedText")


def main():
    for attempt in range(2):
        try:
            out, det = gtx("Hello, how are you today?", "auto", "ar")
            p(f"gtx en->ar OK: {out!r} (detected={det})")
            break
        except Exception as e:
            p(f"gtx attempt {attempt}: {type(e).__name__}: {e}")
            time.sleep(2)
    try:
        out, det = gtx("مرحبا كيف حالك اليوم", "auto", "en")
        p(f"gtx ar->en OK: {out!r} (detected={det})")
    except Exception as e:
        p(f"gtx ar->en FAIL: {type(e).__name__}: {e}")
    try:
        p(f"mymemory en->ar: {mymemory('Hello, how are you today?', 'en|ar')!r}")
    except Exception as e:
        p(f"mymemory FAIL: {type(e).__name__}: {e}")
    # yandex shape
    png = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Zcc09\AppData\Local\Temp\glimpse_probe.png"
    params = {
        "rpt": "imageview",
        "format": "json",
        "request": json.dumps({"blocks": [{"block": "b-page_type_search-by-image__link"}]}),
    }
    with open(png, "rb") as f:
        files = {"upfile": ("blob", f, "image/png")}
        r = S.post("https://yandex.com/images/search", params=params, files=files, timeout=40)
    p(f"yandex status={r.status_code} ct={r.headers.get('content-type')}")
    try:
        j = r.json()
        p("yandex json:", json.dumps(j)[:800])
    except Exception as e:
        p(f"yandex non-json: {e}; body[:300]={r.text[:300]!r}")


if __name__ == "__main__":
    main()
