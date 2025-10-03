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
        "O": "0", "o": "0", "º": "0"
    })
    return (s or "").translate(tbl)

_LABEL_TO_ST: Dict[str, ShardType] = {
    "mystery": ShardType.MYSTERY,
    "ancient": ShardType.ANCIENT,
    "void":    ShardType.VOID,
    "primal":  ShardType.PRIMAL,
    "sacred":  ShardType.SACRED,
}

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
    Returns {ShardType: int} by reading the LEFT shard list.
    Two-pass approach:
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
        # Use a gentle enhance to help word shapes.
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
            x = int(lab["left"][i]); y = int(lab["top"][i])
            w = int(lab["width"][i]); h = int(lab["height"][i])
            words.append({"t": t, "x": x, "y": y, "w": w, "h": h, "cx": x + w / 2, "cy": y + h / 2, "conf": conf})

        if not words:
            return {}

        labels = [w for w in words if w["t"].lower() in _LABEL_TO_ST]
        if not labels:
            # occasionally Tesseract sees "Mystery Shard" as one token; split crude heuristic
            for w in words:
                lw = w["t"].lower()
                if lw.endswith("shard"):
                    head = lw.replace(" shard", "")
                    if head in _LABEL_TO_ST:
                        labels.append({**w, "t": head})
        if not labels:
            return {}

        # -------------------------
        # PASS B: NUMBERS (left rail ROI)
        # -------------------------
        # The shard list sits on the left ~35–45% of the screen across devices.
        roi_x2 = int(W * 0.45)
        roi = base.crop((0, 0, roi_x2, H))  # left rail
        # convert to grayscale + autocontrast + slight sharpen + binary threshold
        num_img = ImageOps.grayscale(roi)
        num_img = ImageOps.autocontrast(num_img)
        num_img = num_img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
        # hard threshold to make digits crisp; 160 is a good mid-point for these UIs
        num_img = num_img.point(lambda p: 255 if p > 160 else 0)

        num_cfg = (
            "--oem 3 --psm 6 "
            "-c tessedit_char_whitelist=0123456789., "
            "-c preserve_interword_spaces=1"
        )
        nd = pytesseract.image_to_data(num_img, output_type=Output.DICT, config=num_cfg)

        nums = []
        for i in range(len(nd["text"])):
            raw = (nd["text"][i] or "").strip()
            if not raw:
                continue
            t = _normalize_digits(raw)
            # re-add spaces check by normalizing for the regex
            t_for_match = t.replace("\u00A0", " ")  # non-breaking space
            if not (_NUM_RE.match(t_for_match) or t_for_match.isdigit()):
                continue
            try:
                conf = float(nd["conf"][i])
            except Exception:
                conf = -1.0
            if conf < 30:
                continue
            x = int(nd["left"][i]); y = int(nd["top"][i])
            w = int(nd["width"][i]); h = int(nd["height"][i])
            # map ROI coords back to full image space for band math
            cx = x + w / 2
            cy = y + h / 2
            nums.append({"t": t, "x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy, "conf": conf})

        if not nums:
            return {}

        # -------------------------
        # MATCH: per label, pick best number LEFT of label in same band
        # -------------------------
        results: Dict[ShardType, int] = {}
        for lab in labels:
            st = _LABEL_TO_ST[lab["t"].lower()]
            # Horizontal band around the label row
            band_top = lab["cy"] - max(22, lab["h"] * 1.1)
            band_bot = lab["cy"] + max(22, lab["h"] * 1.1)

            cands = [n for n in nums if (band_top <= n["cy"] <= band_bot) and (n["cx"] < lab["x"])]
            if not cands:
                # wider tolerance if label/number heights differ (different DPIs)
                cands = [n for n in nums if (abs(n["cy"] - lab["cy"]) <= max(30, lab["h"] * 1.5)) and (n["cx"] < lab["x"])]
            if not cands:
                continue

            # closest by X (to the left) with small confidence bonus
            def score(nw):
                dx = lab["x"] - nw["cx"]
                return dx - (nw["conf"] * 0.4)  # lower better

            best = min(cands, key=score)
            results[st] = max(results.get(st, 0), _to_int(best["t"]))

        return results
    except Exception:
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
