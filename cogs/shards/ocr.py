# cogs/shards/ocr.py
from __future__ import annotations

import io
import re
from typing import Dict, List, Tuple

# Importing here so the cog can still boot if OCR stack is missing.
try:
    import pytesseract  # type: ignore
    from pytesseract import Output  # type: ignore
    from PIL import Image, ImageOps, ImageFilter, ImageDraw  # type: ignore
except Exception:  # pragma: no cover
    pytesseract = None  # type: ignore
    Output = None  # type: ignore
    Image = None  # type: ignore
    ImageOps = None  # type: ignore
    ImageFilter = None  # type: ignore
    ImageDraw = None  # type: ignore

from .constants import ShardType

# Accept "3,584" / "3.584" / "3 584"
_NUM_RE = re.compile(r"^\d{1,5}(?:[.,\s]\d{3})*$")


# ---------------------------
# Public helpers (imported by cog)
# ---------------------------

def ocr_runtime_info() -> Dict[str, str] | None:
    """Return versions of Tesseract / pytesseract / Pillow if available."""
    if pytesseract is None or Image is None:
        return None
    try:
        try:
            tver = str(pytesseract.get_tesseract_version())
        except Exception:
            tver = "unknown"
        return {
            "tesseract_version": tver,
            "pytesseract_version": getattr(pytesseract, "__version__", "unknown"),
            "pillow_version": getattr(Image, "__version__", "unknown"),
        }
    except Exception:
        return None


def ocr_smoke_test() -> Tuple[bool, str]:
    """
    Render '12345', OCR it, and report whether it's read back correctly.
    Returns (ok, raw_text).
    """
    if pytesseract is None or Image is None or ImageDraw is None:
        return (False, "")
    try:
        img = Image.new("L", (200, 60), color=255)
        d = ImageDraw.Draw(img)
        d.text((10, 10), "12345", fill=0)
        txt = pytesseract.image_to_string(
            img,
            config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789",
            timeout=3,
        )
        txt = (txt or "").strip()
        return ("12345" in txt, txt)
    except Exception:
        return (False, "")


def extract_counts_from_image_bytes(data: bytes) -> Dict[ShardType, int]:
    """
    Number-only OCR:
      1) Crop the *left rail* of the screenshot (no word labels).
      2) Grayscale → autocontrast → unsharp → binarize (and also try inverted).
      3) OCR only digits and separators with short timeouts.
      4) Split ROI vertically into 5 equal bands (Myst, Anc, Void, Pri, Sac).
      5) For each band, choose best numeric token (highest conf) near the left.
    Returns {} if OCR stack is unavailable or nothing reasonable was found.
    """
    if pytesseract is None or Image is None or ImageOps is None:
        return {}

    try:
        base = Image.open(io.BytesIO(data))
        base = ImageOps.exif_transpose(base)

        # Scale up small phone screenshots for clarity
        scale = _scale_if_small(base.width, base.height)
        if scale != 1.0:
            base = base.resize((int(base.width * scale), int(base.height * scale)))

        # Try a few crop widths; pick the one that yields the most non-zero bands
        ratios = (0.38, 0.36, 0.46)
        best_counts: Dict[ShardType, int] = {}
        best_score = -1

        for r in ratios:
            roi = _left_rail_crop(base, r)
            counts, score = _read_counts_from_roi(roi, timeout_sec=6)
            if score > best_score:
                best_counts, best_score = counts, score

        # Ensure all shard keys exist
        for st in ShardType:
            best_counts.setdefault(st, 0)

        # If everything is zero, signal "no OCR"
        if sum(best_counts.values()) == 0:
            return {}
        return best_counts
    except Exception:
        return {}


def extract_counts_with_debug(
    data: bytes, timeout_sec: int = 6
) -> Tuple[Dict[ShardType, int], List[Tuple[str, bytes]]]:
    """
    Same as extract_counts_from_image_bytes, but also returns debug images:
    [("roi_gray.png", ...), ("roi_bin.png", ...), ("roi_bin_inv.png", ...)]
    Only the first ratio is exported as debug imagery.
    """
    if pytesseract is None or Image is None or ImageOps is None:
        return ({}, [])

    try:
        base = Image.open(io.BytesIO(data))
        base = ImageOps.exif_transpose(base)

        scale = _scale_if_small(base.width, base.height)
        if scale != 1.0:
            base = base.resize((int(base.width * scale), int(base.height * scale)))

        ratios = (0.42, 0.36, 0.46)

        # Build debug for the first ratio
        roi0 = _left_rail_crop(base, ratios[0])
        gray0, bin0 = _preprocess_roi(roi0)
        dbg: List[Tuple[str, bytes]] = []
        dbg.append(("roi_gray.png", _img_to_png_bytes(gray0)))
        dbg.append(("roi_bin.png", _img_to_png_bytes(bin0)))
        try:
            dbg.append(("roi_bin_inv.png", _img_to_png_bytes(ImageOps.invert(bin0))))
        except Exception:
            pass

        # Choose the best among all ratios
        best_counts: Dict[ShardType, int] = {}
        best_score = -1
        for r in ratios:
            roi = _left_rail_crop(base, r)
            counts, score = _read_counts_from_roi(roi, timeout_sec=timeout_sec)
            if score > best_score:
                best_counts, best_score = counts, score

        for st in ShardType:
            best_counts.setdefault(st, 0)

        return (best_counts, dbg)
    except Exception:
        return ({}, [])


# ---------------------------
# Internal helpers
# ---------------------------

def _scale_if_small(w: int, h: int) -> float:
    if w < 900:
        return 2.0
    if w < 1300:
        return 1.5
    return 1.0


def _left_rail_crop(img: "Image.Image", ratio: float) -> "Image.Image":
    """Crop left portion of the screen where the shard list + numbers live."""
    W, H = img.size
    x2 = int(max(1, min(W, W * ratio)))
    return img.crop((0, 0, x2, H))


def _preprocess_roi(roi: "Image.Image") -> Tuple["Image.Image", "Image.Image"]:
    """
    Return (gray_autocontrast, binarized) images for OCR.
    """
    gray = ImageOps.grayscale(roi)
    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
    # A fixed threshold works well for Raid UI; tweak if needed
    bin_img = gray.point(lambda p: 255 if p > 160 else 0)
    # Thicken thin strokes a touch; improves small numerals like 3/1.
    bin_img = bin_img.filter(ImageFilter.MaxFilter(3))
    return gray, bin_img

def _normalize_digits(s: str) -> str:
    # Fix common OCR slips: l/İ/I → 1, O/º → 0
    tbl = str.maketrans({"l": "1", "I": "1", "İ": "1", "í": "1", "O": "0", "o": "0", "º": "0"})
    return (s or "").translate(tbl)


def _parse_num_token(raw: str) -> int:
    t = _normalize_digits(raw).replace(",", "").replace(".", "").replace(" ", "")
    return int(t) if t.isdigit() else 0

def _score_band_token(txt: str, conf: float) -> Tuple[int, float]:
    """Return a comparable score tuple for band-level OCR picks."""
    cleaned = _normalize_digits(txt).replace(",", "").replace(".", "").replace(" ", "")
    return (len(cleaned), conf)


def _run_psm7_band_pass(
    sub_img_bin: "Image.Image",
    sub_img_gray: "Image.Image",
    timeout_sec: int,
) -> Tuple[str, float] | None:
    """Run the tighter per-band OCR pass and return the best (text, conf)."""
    picks: List[Tuple[str, float]] = []
    for sub_img in (sub_img_bin, sub_img_gray):
        try:
            dd2 = pytesseract.image_to_data(
                sub_img,
                output_type=Output.DICT,
                config="--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789., -c classify_bln_numeric_mode=1",
                timeout=max(2, timeout_sec // 2),
            )
        except Exception:
            continue

        m = len(dd2.get("text", []))
        for j in range(m):
            raw2 = (dd2["text"][j] or "").strip()
            if not raw2:
                continue
            t2 = _normalize_digits(raw2)
            if not (_NUM_RE.match(t2) or t2.isdigit()):
                continue
            try:
                conf2 = float(dd2["conf"][j])
            except Exception:
                conf2 = -1.0
            if conf2 >= 10:
                picks.append((t2, conf2))

    if not picks:
        return None

    return max(picks, key=lambda p: _score_band_token(p[0], p[1]))


def _read_counts_from_roi(roi, timeout_sec: int = 6) -> Tuple[Dict[ShardType, int], int]:
    """
    OCR the ROI and split vertically into 5 bands. We try multiple OCR passes:
    binary → inverted-binary → gray; and two configs (PSM 11 then PSM 6).
    Returns (counts, score) where score = number of bands with nonzero readings.
    """
    gray, bin_img = _preprocess_roi(roi)

    # candidate images to try
    candidates: List[Image.Image] = [bin_img]
    try:
        candidates.append(ImageOps.invert(bin_img))
    except Exception:
        pass
    candidates.append(gray)

    # OCR configs to try (prefer sparse text first)
    cfgs = [
        "--oem 3 --psm 6  -c tessedit_char_whitelist=0123456789., -c preserve_interword_spaces=1 -c classify_bln_numeric_mode=1",
        "--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789., -c preserve_interword_spaces=1 -c classify_bln_numeric_mode=1",
    ]

    tokens: List[Tuple[int, int, float, str]] = []  # (cx, cy, conf, text)
    W, H = bin_img.size
    # Accept up to ~60% of the left rail; still rejects mid-screen counters (e.g., 238/270).
    left_frac = 0.60
    max_x = int(W * left_frac)

    for img in candidates:
        for cfg in cfgs:
            try:
                dd = pytesseract.image_to_data(
                    img, output_type=Output.DICT, config=cfg, timeout=timeout_sec
                )
            except Exception:
                continue

            n = len(dd.get("text", []))
            for i in range(n):
                raw = (dd["text"][i] or "").strip()
                if not raw:
                    continue
                txt = _normalize_digits(raw).replace("\u00A0", " ")
                if not (_NUM_RE.match(txt) or txt.isdigit()):
                    continue
                try:
                    conf = float(dd["conf"][i])
                except Exception:
                    conf = -1.0
                if conf < 18:
                    continue
                x = int(dd["left"][i]); y = int(dd["top"][i])
                w = int(dd["width"][i]); h = int(dd["height"][i])
                cx = x + w // 2; cy = y + h // 2
                if cx > max_x:
                    continue
                tokens.append((cx, cy, conf, txt))

        # If we've found a healthy number of candidates, stop early.
        if len(tokens) >= 8:
            break

    # Split ROI into 5 vertical bands; pick best token per band.
    counts_by_band: List[int] = []
    band_h = H / 5.0
    for band in range(5):
        y0 = band * band_h
        y1 = (band + 1) * band_h
        cands = [(cx, cy, conf, txt) for (cx, cy, conf, txt) in tokens if (y0 <= cy < y1)]
        main_pick: Tuple[str, float] | None = None
        if cands:
            best = max(cands, key=lambda t: _score_band_token(t[3], t[2]))
            main_pick = (best[3], best[2])

        micro_pick: Tuple[str, float] | None = None
        bx0, bx1 = 0, max_x
        by0 = int(y0 + band_h * 0.15)
        by1 = int(y0 + band_h * 0.85)
        try:
            sub = roi.crop((bx0, by0, bx1, by1))
            sub_gray, sub_bin = _preprocess_roi(sub)
            micro_pick = _run_psm7_band_pass(sub_bin, sub_gray, timeout_sec)
        except Exception:
            micro_pick = None

        best_pick = main_pick
        if _score_band_token(*(micro_pick or ("", -1.0))) > _score_band_token(*(best_pick or ("", -1.0))):
            best_pick = micro_pick

        if best_pick is None:
            counts_by_band.append(0)
        else:
            counts_by_band.append(_parse_num_token(best_pick[0]))

    # Map bands to shard types (top→bottom)
    order = [ShardType.MYSTERY, ShardType.ANCIENT, ShardType.VOID, ShardType.PRIMAL, ShardType.SACRED]
    counts: Dict[ShardType, int] = {}
    for st, val in zip(order, counts_by_band):
        counts[st] = max(0, int(val))

    score = sum(1 for v in counts_by_band if v > 0)
    return counts, score


def _img_to_png_bytes(img: "Image.Image") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
