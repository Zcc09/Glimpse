# Glimpse 0.4.1 — OCR follow-up: the snips that still said "no text found"

0.4.0 taught Glimpse to try every installed language. Testing it against real renders found
four more ways a readable snip could still come back empty or garbled — all fixed:

- **One upscale factor was a lottery.** Tesseract's Arabic-script model read a Persian line
  at 1.0× and 1.3×, returned *nothing* at 1.8× (the only factor we tried) and read again at
  2.5× — same image, same model; its line-finding just misses at certain sizes. Glimpse now
  tries 1.0× / 1.3× / 2.5× and gives every variant the full language list (the run budget
  used to be spent on the original size before the upscale was ever attempted).
- **The Latin family was capped too early.** A six-language cap meant Turkish and Vietnamese
  were read by an English model with mangled diacritics (`qok`, `mu6n`). Latin languages are
  now tried in batches, each anchored by English: Turkish and Vietnamese read at 96 % with
  every diacritic intact.
- **Within one pass, order decides the diacritics.** `eng+tur+vie+ind+nld+pol` reads Turkish
  and Vietnamese at ~96; the same languages with the Dutch/Polish models earlier give ~93.
  The batch order is now the one that reads correctly.
- **Windows OCR stopped being trusted just because it was confident.** With English language
  packs it returns accented text it cannot have read (`Bugün hava qok güzel`), and it used to
  win by looking clean. It now only ends the search for plain-ASCII reads; anything with
  accents is checked against Tesseract's models, which do have them.

Verified by test: Chinese · Japanese · Korean · Russian · Greek · Hebrew · Hindi · Arabic ·
Urdu · **Persian** · **Turkish** · **Vietnamese** · German · French · Spanish · English, each
rendered and read end-to-end, plus your own `中文` screenshot as a fixture. Average ~1.2 s per
snip; the longest (Hindi/Chinese, where six Latin-ish passes have to fail first) takes ~4.5 s.
