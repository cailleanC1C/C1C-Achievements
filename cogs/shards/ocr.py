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
      2) Grayscale → autocontrast → unsharp → binarize (both polarities).
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
        ratios = (0.36, 0.40, 0.44)
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
    [("roi_gray.png", ...), ("roi_white_on_black.png", ...), ("roi_black_on_white.png", ...)]
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

        ratios = (0.40, 0.36, 0.44)

        # Build debug for the first ratio
        roi0 = _left_rail_crop(base, ratios[0])
        gray0, bin_w_on_b, bin_b_on_w = _preprocess_roi_dual(roi0)
        dbg: List[Tuple[str, bytes]] = [
            ("roi_gray.png", _img_to_png_bytes(gray0)),
            ("roi_white_on_black.png", _img_to_png_bytes(bin_w_on_b)),
            ("roi_black_on_white.png", _img_to_png_bytes(bin_b_on_w)),
        ]

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


def _preprocess_roi_dual(roi: "Image.Image") -> Tuple["Image.Image", "Image.Image", "Image.Image"]:
    """
    Return (gray_autocontrast, bin_white_on_black, bin_black_on_white) images for OCR.
    We try both polarities because Raid's UI digits are white on dark.
    """
    gray = ImageOps.grayscale(roi)
    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))

    # Threshold tuned for Raid UI; try both polarities
    bin_white_on_black = gray.point(lambda p: 255 if p > 160 else 0)  # current style (white digits)
    bin_black_on_white = gray.point(lambda p: 0 if p > 160 else 255)  # inverted (black digits)
    return gray, bin_white_on_black, bin_black_on_white


def _normalize_digits(s: str) -> str:
    # Fix common OCR slips: l/İ/I → 1, O/º → 0
    tbl = str.maketrans({"l": "1", "I": "1", "İ": "1", "í": "1", "O": "0", "o": "0", "º": "0"})
    return (s or "").translate(tbl)


def _parse_num_token(raw: str) -> int:
    t = _normalize_digits(raw).replace(",", "").replace(".", "").replace(" ", "")
    return int(t) if t.isdigit() else 0


def _tesseract_data(img: "Image.Image", psm: int, timeout_sec: int):
    cfg = (
        f"--oem 3 --psm {psm} "
        "-c tessedit_char_whitelist=0123456789., "
        "-c preserve_interword_spaces=1 "
        "-c classify_bln_numeric_mode=1"
    )
    return pytesseract.image_to_data(img, output_type=Output.DICT, config=cfg, timeout=timeout_sec)


def _read_counts_from_roi(roi, timeout_sec: int = 6) -> Tuple[Dict[ShardType, int], int]:
    """
    OCR the ROI and split vertically into 5 bands. For each band, pick the best numeric token.
    Returns (counts, score) where score = number of bands with nonzero readings.
    """
    gray, bin_w_on_b, bin_b_on_w = _preprocess_roi_dual(roi)

    W, H = gray.size
    max_x = int(W * 0.60)  # avoid right-side counters like 238/270

    # collect tokens from both polarities and two PSMs (block + sparse)
    tokens: List[Tuple[int, int, float, str]] = []  # (cx, cy, conf, text)

    def _harvest(dd):
        for i in range(len(dd.get("text", []))):
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
            if conf < 20:  # relaxed a bit
                continue
            x = int(dd["left"][i])
            y = int(dd["top"][i])
            w = int(dd["width"][i])
            h = int(dd["height"][i])
            cx = x + w // 2
            cy = y + h // 2
            if cx > max_x:
                continue
            tokens.append((cx, cy, conf, txt))

    # Try: PSM 6 (block) and PSM 11 (sparse), both polarities.
    try:
        _harvest(_tesseract_data(bin_w_on_b, psm=6, timeout_sec=timeout_sec))
    except Exception:
        pass
    try:
        _harvest(_tesseract_data(bin_w_on_b, psm=11, timeout_sec=timeout_sec))
    except Exception:
        pass
    try:
        _harvest(_tesseract_data(bin_b_on_w, psm=6, timeout_sec=timeout_sec))
    except Exception:
        pass
    try:
        _harvest(_tesseract_data(bin_b_on_w, psm=11, timeout_sec=timeout_sec))
    except Exception:
        pass

    # Split ROI into 5 vertical bands, pick best token per band by confidence (then length)
    counts_by_band: List[int] = []
    band_h = H / 5.0
    for band in range(5):
        y0 = band * band_h
        y1 = (band + 1) * band_h
        cands = [(cx, cy, conf, txt) for (cx, cy, conf, txt) in tokens if y0 <= cy < y1]
        if not cands:
            counts_by_band.append(0)
            continue
        best = max(cands, key=lambda t: (t[2], len(t[3])))
        counts_by_band.append(_parse_num_token(best[3]))

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
