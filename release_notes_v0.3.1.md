# Glimpse 0.3.1 — packaging cleanup

Maintenance release; no feature changes to 0.3.0's all-language OCR or the tabbed Options window.

- The bundled OCR engine folder ships only engine/runtime files now: leftover test images from
  building 0.3.0 were removed, and both the packaging spec and the bundle script carry a
  whitelist so scratch files can never ride into a release again.
- `vendor/tesseract` is pruned automatically on every `fetch_tesseract.py` run.

Nothing to do on your side: same features, same settings, same data folder.
