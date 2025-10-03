# cogs/shards/ocr.py
from __future__ import annotations
import io, re
from typing import Dict, Optional

from .constants import ShardType

# Accept "1,610" / "1.610" / "1 610" etc.
_NUM_RE = re.compile(r"^\d{1,4}(?:[.,\s]\d{3})*$")


def _normalize_digits(s: str) -> str:
    # fix common OCR slips: l/İ/I → 1, O/º → 0, stray spaces inside thousand groups
    tbl = str.maketrans({
        "l": "1", "I": "1", "İ": "1", "í": "1",
        "O": "0", "o": "0", "º": "0",
    })
    return (s or "").translate(tbl)


_LABEL_TO_ST: Dict[str, ShardType] = {
    "mystery": ShardType.MYSTERY,
    "ancient": ShardType.ANCIENT,
    "void": ShardType.VOID,
    "primal": ShardType.PRIMAL,
    "sacred": ShardType.SACRED,
}


def _label_key(raw: str) -> Optional[str]:
    cleaned = re.sub(r"[^a-z]", "", (raw or "").lower())
    for suffix in ("shards", "shard"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    cleaned = cleaned.rstrip("s")
    return cleaned if cleaned in _LABEL_TO_ST else None


def _to_int(num_text: str) -> int:
    s = _normalize_digits(num_text).replace(",", "").replace(".", "").replace(" ", "")
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
    Read the five shard counts directly from the left rail (top→bottom), no labels.
    Works for portrait & landscape. Returns {ShardType: int}.
    """
    try:
        import pytesseract
        from pytesseract import Output
        from PIL import Image, ImageOps, ImageFilter
    except Exception:
        return {}

    try:
        # 1) load & normalize
        base = Image.open(io.BytesIO(data))
        base = ImageOps.exif_transpose(base)
        scale = _scale_if_small(base.width, base.height)
        if scale != 1.0:
            base = base.resize((int(base.width * scale), int(base.height * scale)))

        W, H = base.width, base.height

        # helper: OCR numbers from a crop
        def _ocr_numbers(crop_box):
            roi = base.crop(crop_box)
            cW, cH = roi.width, roi.height
            img = ImageOps.grayscale(roi)
            img = ImageOps.autocontrast(img)
            img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
            img = img.point(lambda p: 255 if p > 160 else 0)
            cfg = ("--oem 3 --psm 6 "
                   "-c tessedit_char_whitelist=0123456789., "
                   "-c preserve_interword_spaces=1 "
                   "-c classify_bln_numeric_mode=1")
            dd = pytesseract.image_to_data(img, output_type=Output.DICT, config=cfg)

            toks = []
            for i in range(len(dd["text"])):
                raw = (dd["text"][i] or "").strip()
                if not raw:
                    continue
                t = _normalize_digits(raw).replace("\u00A0", " ")
                if not (_NUM_RE.match(t) or t.isdigit()):
                    continue
                try:
                    conf = float(dd["conf"][i])
                except Exception:
                    conf = -1.0
                if conf < 30:
                    continue
                x = int(dd["left"][i]); y = int(dd["top"][i])
                w = int(dd["width"][i]); h = int(dd["height"][i])
                # drop outliers (buttons/headers/noise)
                if h < cH * 0.025 or h > cH * 0.18:
                    continue
                toks.append({"t": t, "x": x, "y": y, "w": w, "h": h,
                             "cx": x + w / 2, "cy": y + h / 2, "conf": conf})
            return toks, cH

        # helper: cluster tokens into rows, pick best per row
        def _cluster_rows(tokens, crop_h):
            if not tokens:
                return []
            tokens = sorted(tokens, key=lambda r: r["cy"])
            rows, cur = [], []
            tol = max(10, crop_h * 0.07)
            lasty = None
            for tk in tokens:
                if lasty is None or abs(tk["cy"] - lasty) <= tol:
                    cur.append(tk)
                    lasty = tk["cy"] if lasty is None else (lasty * 0.6 + tk["cy"] * 0.4)
                else:
                    rows.append(cur); cur = [tk]; lasty = tk["cy"]
            if cur:
                rows.append(cur)
            # pick best: conf desc, height desc, leftmost
            return [sorted(r, key=lambda z: (-z["conf"], -z["h"], z["cx"]))[0] for r in rows]

        # 2) try three left-rail crops
        crops = [(0, 0, int(W * frac), H) for frac in (0.35, 0.42, 0.50)]
        best_rows = []
        for box in crops:
            toks, cH = _ocr_numbers(box)
            rows = _cluster_rows(toks, cH)
            if len(rows) >= 5:
                best_rows = rows
                break

        # last-chance: wider left mask
        if len(best_rows) < 5:
            toks, cH = _ocr_numbers((0, 0, int(W * 0.60), H))
            best_rows = _cluster_rows(toks, cH)

        if len(best_rows) < 5:
            return {}

        # 3) map top five rows to shard order
        best_rows = sorted(best_rows, key=lambda r: r["cy"])[:5]
        vals = [_to_int(r["t"]) for r in best_rows]
        order = [ShardType.MYSTERY, ShardType.ANCIENT, ShardType.VOID, ShardType.PRIMAL, ShardType.SACRED]
        result = {st: 0 for st in order}
        for st, v in zip(order, vals):
            result[st] = v
        return result
    except Exception:
        return {}
