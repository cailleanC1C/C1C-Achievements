# cogs/shards/ocr.py
from __future__ import annotations
import io, re
from typing import Dict, Optional

from .constants import ShardType

# Accept "1,610" / "1.610" etc.
_NUM_RE = re.compile(r"^\d{1,4}(?:[.,]\d{3})*$")

_LABEL_TO_ST: Dict[str, ShardType] = {
    "mystery": ShardType.MYSTERY,
    "ancient": ShardType.ANCIENT,
    "void":    ShardType.VOID,
    "primal":  ShardType.PRIMAL,
    "sacred":  ShardType.SACRED,
}

def _to_int(num_text: str) -> int:
    s = (num_text or "").replace(",", "").replace(".", "")
    return int(s) if s.isdigit() else 0

def _scale_if_small(w: int, h: int) -> float:
    # Small mobile screenshots benefit from a 1.5–2.0x scale before OCR.
    if w < 900:
        return 2.0
    if w < 1300:
        return 1.5
    return 1.0

def extract_counts_from_image_bytes(data: bytes) -> Dict[ShardType, int]:
    """
    Returns {ShardType: int}. If Tesseract/Pillow are not available, returns {} (safe fallback).
    Strategy:
      1) OCR word boxes (image_to_data).
      2) Find label token positions ('Mystery', 'Ancient', ...).
      3) For each label, choose the highest-confidence number token to its LEFT on the same row band.
    """
    try:
        import pytesseract
        from pytesseract import Output
        from PIL import Image, ImageOps
    except Exception:
        return {}

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # fix orientation
        scale = _scale_if_small(img.width, img.height)
        if scale != 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)))

        # word boxes
        cfg = "--oem 3 --psm 6"
        dd = pytesseract.image_to_data(img, output_type=Output.DICT, config=cfg)

        n = len(dd["text"])
        words = []
        for i in range(n):
            text = (dd["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(dd["conf"][i])
            except Exception:
                conf = -1.0
            if conf < 35:  # drop low confidence noise
                continue
            x = int(dd["left"][i]); y = int(dd["top"][i])
            w = int(dd["width"][i]); h = int(dd["height"][i])
            words.append({"t": text, "x": x, "y": y, "w": w, "h": h, "cx": x + w / 2, "cy": y + h / 2, "conf": conf})

        if not words:
            return {}

        # Build quick lookups
        labels = [w for w in words if w["t"].lower() in _LABEL_TO_ST]
        numbers = [w for w in words if _NUM_RE.match(w["t"])]

        # If Tesseract split "Mystery" and "Shard", that's OK—we match the 'Mystery' token only.
        # For each label, pick the best number to its LEFT in the same horizontal band.
        results: Dict[ShardType, int] = {}
        for lab in labels:
            st = _LABEL_TO_ST[lab["t"].lower()]
            band_top = lab["cy"] - max(18, lab["h"] * 0.9)
            band_bot = lab["cy"] + max(18, lab["h"] * 0.9)

            # candidates left of the label, within band
            cands = [
                num for num in numbers
                if (band_top <= num["cy"] <= band_bot) and (num["cx"] < lab["x"])
            ]
            if not cands:
                # fallback: small drift tolerance
                cands = [
                    num for num in numbers
                    if (abs(num["cy"] - lab["cy"]) <= max(24, lab["h"])) and (num["cx"] < lab["x"])
                ]
            if not cands:
                continue

            # choose the closest on X (to the left) with a small bonus for higher conf
            def score(nw):
                dx = (lab["x"] - nw["cx"])
                return (dx) - (nw["conf"] * 0.5)  # lower is better
            best = min(cands, key=score)
            results[st] = max(results.get(st, 0), _to_int(best["t"]))

        return results
    except Exception:
        return {}
