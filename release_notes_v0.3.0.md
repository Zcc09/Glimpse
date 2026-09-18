# Glimpse 0.3.0 — all-language OCR + a proper Options window

## Read text in (almost) any language

Text recognition now has three engines behind one setting (Options → **Text (OCR)**):

- **Windows OCR** — the built-in engine, unchanged but smarter: with no language picked it now
  runs **every installed recognizer language** and keeps the best-looking result, so any Windows
  language pack you add is used automatically.
- **Tesseract** — now **bundled with Glimpse**. No install step: the engine ships inside the
  app (Apache-2.0, built from conda-forge) together with English and orientation data.
  The Options window lists all **126** available languages with their download state — tick
  what you need and press *Download ticked*, or *Download all common* (~30 languages, ~60 MB).
  Data lands in `%APPDATA%\Glimpse\tessdata` and works offline from then on. Arabic, Urdu,
  Persian, Russian, Chinese, Japanese, Korean, Hindi, Hebrew, Thai, Greek… all of it.
- **Auto** (new default) — Windows OCR first (it is fast), Tesseract only when the Windows
  result doesn't look like text. Snipping Arabic or Russian text on a machine whose only
  Windows pack is English just works.

Also new around it:

- Dark-mode snips (light text on dark UI) are inverted automatically for both engines.
- Small/thin selections are upscaled smartly before reading — much better on 12–18 px UI text.
- Results are **scored**: if every engine returns something that doesn't look like text, the
  result window says *low confidence* instead of showing gibberish as if it were the answer.
- **Test OCR** button: renders a sample and reports which engine read it, in which language.
- `--selftest` now covers the bundled Tesseract engine (English + a non-Latin script when its
  data is present), so every build proves its OCR stack.

## Options window: tabs, and resizable

The settings window is no longer one long scroll. It is a resizable, tabbed window that
remembers its size and the tab you left it on:

**General · Hotkeys · Text (OCR) · Translation · Visual search · Audio · Updates · App**

Hotkey conflicts still land you back on the Hotkeys tab with the reason; Apply saves without
closing.

## Notes

- Your data folder is untouched by the update; language data you download stays.
- Already have Tesseract installed system-wide? Glimpse still prefers its own bundled copy,
  which is verified to match the language files it manages.
