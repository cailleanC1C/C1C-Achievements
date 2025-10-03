# cogs/shards/ocr.py
from __future__ import annotations
import io, re
from typing import Dict, List, Optional

from .constants import ShardType

# Accept "3,584" / "3.584" / "3 584"
_NUM_RE = re.compile(r"^\d{1,4}(?:[.,\s]\d{3})*$")

ORDER_TOP_TO_BOTTOM: List[ShardType] = [
    ShardType.MYSTERY,
    ShardType.ANCIENT,
    ShardType.VOID,
    ShardType.PRIMAL,
    ShardType.SACRED,
]

def _normalize_digits(s: str) -> str:
    # common OCR slips → digits
    tbl = str.maketrans({
        "l": "1", "I": "1", "İ": "1", "í": "1",
        "O": "0", "o": "0", "º": "0",
        "\u00A0": " ",  # NBSP → space
    })
    return (s or "").translate(tbl)

def _to_int(num_text: str) -> int:
    s = _normalize_digits(num_text).replace(",", "").replace(".", "").replace(" ", "")
    return int(s) if s.isdigit() else 0

def _scale_if_small(w: int, h: int) -> float:
    if w < 900:   # small phone screenshot
        return 2.0
    if w < 1300:
        return 1.5
    return 1.0

def _preprocess_roi(roi):
    """grayscale → autocontrast → sharpen → invert (dark text on light bg)"""
    from PIL import ImageOps, ImageFilter
    img = ImageOps.grayscale(roi)
    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
    img = ImageOps.invert(img)
    return img

def _ocr_tokens(img, cfg: str):
    """Return list of numeric tokens with geometry using image_to_data."""
    import pytesseract
    from pytesseract import Output

    dd = pytesseract.image_to_data(img, output_type=Output.DICT, config=cfg)
    tokens: List[dict] = []
    n = len(dd["text"])
    for i in range(n):
        raw = (dd["text"][i] or "").strip()
        if not raw:
            continue
        t = _normalize_digits(raw)
        # keep only numeric-like strings
        if not (_NUM_RE.match(t) or t.isdigit()):
            continue
        try:
            conf = float(dd["conf"][i])
        except Exception:
            conf = -1.0
        if conf < 5:  # be permissive; small UI digits score low
            continue
        x = int(dd["left"][i]); y = int(dd["top"][i])
        w = int(dd["width"][i]); h = int(dd["height"][i])
        tokens.append({
            "t": t, "conf": conf,
            "x": x, "y": y, "w": w, "h": h,
            "cx": x + w / 2, "cy": y + h / 2,
        })
    return tokens

def _cluster_rows(tokens: List[dict], img_h: int) -> List[dict]:
    """Group tokens by vertical bands into up to 5 rows (top→bottom)."""
    if not tokens:
        return []
    tokens = sorted(tokens, key=lambda k: k["cy"])
    # estimate band height
    hs = sorted(t["h"] for t in tokens)
    med_h = hs[len(hs) // 2] if hs else max(20, img_h // 40)
    band = max(22, int(med_h * 1.6))

    rows: List[List[dict]] = []
    cur: List[dict] = [tokens[0]]
    last_y = tokens[0]["cy"]

    for t in tokens[1:]:
        if abs(t["cy"] - last_y) <= band:
            cur.append(t)
        else:
            rows.append(cur)
            cur = [t]
        last_y = t["cy"]
    rows.append(cur)

    # choose best numeric per row
    picked: List[dict] = []
    for group in rows:
        # score: wider & longer & higher conf preferred
        def score(g):
            return -(len(g["t"]) * 2 + g["w"] * 0.5 + g["conf"] * 0.2)
        best = sorted(group, key=score)[0]
        picked.append({"cy": int(sum(t["cy"] for t in group) / len(group)),
                       "text": best["t"]})
    # top→bottom
    picked.sort(key=lambda k: k["cy"])
    # keep first 5 rows; if fewer, return fewer
    return picked[:5]

def _fallback_line_scan(img):
    """If token boxes fail, use image_to_string and grab one number per visual line."""
    import pytesseract
    text = pytesseract.image_to_string(
        img,
        config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789., "
    ) or ""
    rows: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.search(r"[0-9][0-9.,\s]*[0-9]", _normalize_digits(s))
        if m:
            rows.append(m.group(0))
    return rows[:5]

def extract_counts_from_image_bytes(data: bytes) -> Dict[ShardType, int]:
    """Return {ShardType: int} by scanning the left shard rail top→bottom."""
    try:
        import pytesseract  # noqa: F401  (ensures import failure falls through)
        from PIL import Image, ImageOps
    except Exception:
        return {}

    try:
        base = Image.open(io.BytesIO(data))
        base = ImageOps.exif_transpose(base)

        # scale small screenshots for clarity
        scale = _scale_if_small(base.width, base.height)
        if scale != 1.0:
            base = base.resize((int(base.width * scale), int(base.height * scale)))

        W, H = base.width, base.height

        # Fixed left-rail crop: 55% of width works across both layouts
        roi_x2 = int(W * 0.55)
        roi = base.crop((0, 0, roi_x2, H))
        num_img = _preprocess_roi(roi)

        # Try multiple PSMs for robustness
        cfgs = [
            "--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789., -c preserve_interword_spaces=1 -c classify_bln_numeric_mode=1",
            "--oem 3 --psm 6  -c tessedit_char_whitelist=0123456789., -c preserve_interword_spaces=1 -c classify_bln_numeric_mode=1",
            "--oem 3 --psm 7  -c tessedit_char_whitelist=0123456789., -c preserve_interword_spaces=1 -c classify_bln_numeric_mode=1",
        ]

        tokens: List[dict] = []
        for cfg in cfgs:
            tokens = _ocr_tokens(num_img, cfg)
            if tokens:
                break

        rows: List[dict] = _cluster_rows(tokens, H)
        if not rows:
            # string fallback (no geometry); build pseudo rows
            ls = _fallback_line_scan(num_img)
            rows = [{"cy": i, "text": s} for i, s in enumerate(ls)]

        # Map rows to shard order (top→bottom). If we got fewer than 5, fill with 0.
        results: Dict[ShardType, int] = {}
        for idx, st in enumerate(ORDER_TOP_TO_BOTTOM):
            if idx < len(rows):
                results[st] = _to_int(rows[idx]["text"])
            else:
                results[st] = 0

        return results
    except Exception:
        # On any unexpected error we fail safe.
        return {}
