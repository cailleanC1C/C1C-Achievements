# OCR System Overview

## **1️⃣ Overview**
- The current OCR system uses template-based corner/icon detection → ROI extraction → binarization → Tesseract OCR.
- Runs on Render (free tier), `tesseract-ocr 5.5.0`, `pytesseract 0.3.13`, `pillow 10.4.0`.

## **2️⃣ Entry points & debug**
- Commands: `!ocrdebug`, `!build`
- What `!build` displays: python version, commit hashes, icon dir, corner-match presence.
- What `!ocrdebug` does: generates `debug_left_rail.png` showing green ROI boxes.
- Key log lines:
  - `OCR template loaded: ...`
  - `OCR corner match ...`
  - `OCR icon matches ...`
  - `[ocrdebug] locator used: icon|corner|none | icons=N`

## **3️⃣ Assets**
- Path: `modules/achievements/assets/ocr/icons/`
- Required corner template files (PNG, lowercase): `mystery.png`, `ancient.png`, `void.png`, `primal.png`, `sacred.png`
- Guidance: cropped top-left tile corners, sharp, no numbers.

## **4️⃣ Pipeline internals**
- Locator: `modules/achievements/locators/left_rail.py`
- `match_icons`, `match_corners`, `tiles_to_number_rois`, `corners_to_number_rois`
- ROI offset logic (+2 % Y).
- OCR: `modules/achievements/ocr_pipeline.py`
- `_prep_bin` (adaptive threshold)
- digit whitelist + confidence floor 35
- lenient fallback to legacy when digits are dropped.

## **5️⃣ Current state**
- ✅ Loads templates, draws boxes, logs cleanly.
- ⚠️ Inconsistent matches across resolutions; two rows may miss; ROIs drift.
- Decision: **pause OCR**, keep debug active, gate under feature flag `ocr_shards`.

## **6️⃣ Next-step plan**
- One anchor → derive 5 ROIs by percentages.
- Retain binarization + whitelist.
- Keep lenient fallback + logging.
- Add regression pack with “golden” screenshots.

## **7️⃣ Verification**
- `!build` → `corner-match present: True`
- `!ocrdebug` → 5 green boxes + log scores.
