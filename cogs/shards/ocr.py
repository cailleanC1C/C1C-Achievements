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
    if cleaned.endswith("shards"):
        cleaned = cleaned[:-6]
    elif cleaned.endswith("shard"):
        cleaned = cleaned[:-5]
    if cleaned.endswith("s"):
        cleaned = cleaned[:-1]
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
    """OCR shard counts from a screenshot.

    Returns {ShardType: int} by reading the shard list rail. The OCR work happens
    in two passes:
      • Pass A (labels): full image, psm 6 — find 'Mystery/Ancient/Void/Primal/Sacred'
      • Pass B (numbers): left-rail ROI, grayscale+threshold, digit whitelist — find counts
    """
    try:
        import pytesseract
        from pytesseract import Output
        from PIL import Image, ImageOps, ImageFilter
    except Exception:
        return {}

    try:
        # --- load & normalize orientation ---
        base = Image.open(io.BytesIO(data))
        base = ImageOps.exif_transpose(base)

        # --- scale up small images (phones) for OCR clarity ---
        scale = _scale_if_small(base.width, base.height)
        if scale != 1.0:
            base = base.resize((int(base.width * scale), int(base.height * scale)))

        W, H = base.width, base.height

        # -------------------------
        # PASS A: LABELS (words)
        # -------------------------
        lab_img = ImageOps.autocontrast(base)
        lab_cfg = "--oem 3 --psm 6"
        lab = pytesseract.image_to_data(lab_img, output_type=Output.DICT, config=lab_cfg)

        words = []
        for i in range(len(lab["text"])):
            t = (lab["text"][i] or "").strip()
            if not t:
                continue
            try:
                conf = float(lab["conf"][i])
            except Exception:
                conf = -1.0
            if conf < 35:
                continue
            x = int(lab["left"][i])
            y = int(lab["top"][i])
            w = int(lab["width"][i])
            h = int(lab["height"][i])
            words.append({
                "t": t,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "cx": x + w / 2,
                "cy": y + h / 2,
                "conf": conf,
            })

        if not words:
            return {}

        cand_labels = []
        for w in words:
            key = _label_key(w["t"])
            if not key:
                continue
            cand_labels.append({**w, "label": key})

        if not cand_labels:
            return {}

        labels_by_type: Dict[ShardType, Dict[str, object]] = {}
        for lab in cand_labels:
            st = _LABEL_TO_ST[lab["label"]]
            prev = labels_by_type.get(st)
            if not prev or lab["conf"] > prev["conf"]:
                labels_by_type[st] = lab

        labels = list(labels_by_type.values())
        if not labels:
            return {}

        # -------------------------
        # PASS B: NUMBERS (left rail ROI)
        # -------------------------
        max_label_edge = max(lab["x"] + lab["w"] for lab in labels)
        roi_x2 = min(W, int(max(W * 0.6, max_label_edge + W * 0.2)))
        roi = base.crop((0, 0, roi_x2, H))

        num_img = ImageOps.grayscale(roi)
        num_img = ImageOps.autocontrast(num_img)
        num_img = num_img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
        num_img = num_img.point(lambda p: 255 if p > 160 else 0)

        num_cfg = (
            "--oem 3 --psm 6 "
            "-c tessedit_char_whitelist=0123456789., "
            "-c preserve_interword_spaces=1 "
            "-c classify_bln_numeric_mode=1"
        )
        nd = pytesseract.image_to_data(num_img, output_type=Output.DICT, config=num_cfg)

        nums = []
        for i in range(len(nd["text"])):
            raw = (nd["text"][i] or "").strip()
            if not raw:
                continue
            t = _normalize_digits(raw)
            t_for_match = t.replace("\u00A0", " ")  # non-breaking space
            if not (_NUM_RE.match(t_for_match) or t_for_match.isdigit()):
                continue
            try:
                conf = float(nd["conf"][i])
            except Exception:
                conf = -1.0
            if conf < 30:
                continue
            x = int(nd["left"][i])
            y = int(nd["top"][i])
            w = int(nd["width"][i])
            h = int(nd["height"][i])
            nums.append({
                "t": t,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "cx": x + w / 2,
                "cy": y + h / 2,
                "conf": conf,
            })

        if not nums:
            return {}

        # -------------------------
        # MATCH labels to numbers (allow left OR right of label)
        # -------------------------
        results: Dict[ShardType, int] = {}
        for lab in labels:
            st = _LABEL_TO_ST[lab["label"]]
            band_top = lab["cy"] - max(22, lab["h"] * 1.2)
            band_bot = lab["cy"] + max(22, lab["h"] * 1.2)

            cands = [n for n in nums if band_top <= n["cy"] <= band_bot]
            if not cands:
                cands = [n for n in nums if abs(n["cy"] - lab["cy"]) <= max(32, lab["h"] * 1.6)]
            if not cands:
                continue

            anchor_x = lab["x"] + (lab["w"] / 2)
            max_dx = max(lab["w"] * 6, W * 0.28)
            cands = [n for n in cands if abs(n["cx"] - anchor_x) <= max_dx]
            if not cands:
                continue

            def score(nw: Dict[str, float]) -> float:
                dx = abs(nw["cx"] - anchor_x)
                return dx - (nw["conf"] * 0.4)  # lower is better

            best = min(cands, key=score)
            results[st] = max(results.get(st, 0), _to_int(best["t"]))

        if not results:
            return {}

        for st in ShardType:
            results.setdefault(st, 0)

        return results
    except Exception:
        return {}
