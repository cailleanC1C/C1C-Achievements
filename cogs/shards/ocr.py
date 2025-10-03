# cogs/shards/ocr.py
from __future__ import annotations

import io
import re
from typing import Dict, List, Optional, Tuple

# Local enum
from .constants import ShardType

# ---------- Robust numeric parsing ----------
# Accept "1,610" / "1.610" / "1 610" / "1610"
_NUM_RE = re.compile(r"^\d{1,4}(?:[.,\s]\d{3})*$")


def _normalize_digits(s: str) -> str:
    """
    Fix common OCR slips: l/İ/I → 1, O/º → 0. Keep punctuation for grouping.
    """
    tbl = str.maketrans(
        {
            "l": "1",
            "I": "1",
            "İ": "1",
            "í": "1",
            "O": "0",
            "o": "0",
            "º": "0",
        }
    )
    return (s or "").translate(tbl)


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


# Map normalized label → ShardType
_LABEL_TO_ST: Dict[str, ShardType] = {
    "mystery": ShardType.MYSTERY,
    "ancient": ShardType.ANCIENT,
    "void": ShardType.VOID,
    "primal": ShardType.PRIMAL,
    "sacred": ShardType.SACRED,
}


def _label_key(raw: str) -> Optional[str]:
    """
    Normalize a token to a shard label. Handles 'Ancient', 'Ancient Shard', 'Ancient Shards', etc.
    Returns canonical key (e.g., 'ancient') or None if not a shard label.
    """
    cleaned = re.sub(r"[^a-z]", "", (raw or "").lower())
    for suffix in ("shards", "shard"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    cleaned = cleaned.rstrip("s")
    return cleaned if cleaned in _LABEL_TO_ST else None


# ---------- OCR core ----------


def extract_counts_from_image_bytes(data: bytes) -> Dict[ShardType, int]:
    """
    OCR shard counts from a screenshot.

    Strategy:
      1) Run a full-image pass for labels (pytesseract.image_to_data, psm 6).
      2) Build a left-rail ROI for numbers, binarize & digit-whitelist OCR.
      3) Match numbers to labels: for each label, select the closest number to the LEFT in the same horizontal band.
      4) If labels fail, fall back to "5 rows of numbers" heuristic (top→bottom = Myst, Anc, Void, Pri, Sac).

    Returns {ShardType: int}. Missing types default to 0.
    """
    try:
        import pytesseract
        from pytesseract import Output
        from PIL import Image, ImageOps, ImageFilter
    except Exception:
        # OCR stack not available → return empty (caller will handle manual entry).
        return {}

    try:
        # Load & normalize
        base = Image.open(io.BytesIO(data))
        base = ImageOps.exif_transpose(base)

        # Scale small images for better OCR
        scale = _scale_if_small(base.width, base.height)
        if scale != 1.0:
            base = base.resize((int(base.width * scale), int(base.height * scale)))

        W, H = base.width, base.height

        # -------------------------
        # PASS A: LABELS (full image words)
        # -------------------------
        lab_img = ImageOps.autocontrast(base)
        lab_cfg = "--oem 3 --psm 6"
        lab = pytesseract.image_to_data(lab_img, output_type=Output.DICT, config=lab_cfg)

        words: List[Dict[str, float]] = []
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
            words.append(
                {
                    "t": t,
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "cx": x + w / 2,
                    "cy": y + h / 2,
                    "conf": conf,
                }
            )

        # Candidate labels
        cand_labels: List[Dict[str, float]] = []
        for w in words:
            key = _label_key(w["t"])
            if key:
                cand_labels.append({**w, "label": key})

        # Resolve one best token per shard type (highest conf)
        labels: List[Dict[str, float]] = []
        if cand_labels:
            by_type: Dict[ShardType, Dict[str, float]] = {}
            for lab in cand_labels:
                st = _LABEL_TO_ST[lab["label"]]
                prev = by_type.get(st)
                if not prev or lab["conf"] > prev["conf"]:
                    by_type[st] = lab
            labels = list(by_type.values())

        # -------------------------
        # PASS B: NUMBERS (left rail ROI)
        # -------------------------
        # Determine ROI width: left 45%–60%, but at least a bit past the farthest label we found
        if labels:
            max_label_edge = max(lab["x"] + lab["w"] for lab in labels)
            roi_x2 = min(W, int(max(W * 0.55, max_label_edge + W * 0.20)))
        else:
            roi_x2 = int(W * 0.5)
        roi_x2 = max(roi_x2, int(W * 0.35))
        roi = base.crop((0, 0, roi_x2, H))

        # Enhance digits
        num_img = ImageOps.grayscale(roi)
        num_img = ImageOps.autocontrast(num_img)
        num_img = num_img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
        # hard threshold to make digits crisp; 160 is a decent mid-point for this UI
        num_img = num_img.point(lambda p: 255 if p > 160 else 0)

        num_cfg = (
            "--oem 3 --psm 6 "
            "-c tessedit_char_whitelist=0123456789., "
            "-c preserve_interword_spaces=1 "
            "-c classify_bln_numeric_mode=1"
        )
        nd = pytesseract.image_to_data(num_img, output_type=Output.DICT, config=num_cfg)

        nums: List[Dict[str, float]] = []
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
            nums.append(
                {
                    "t": t,
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "cx": x + w / 2,
                    "cy": y + h / 2,
                    "conf": conf,
                }
            )

        if not nums:
            return {}

        results: Dict[ShardType, int] = {}

        # -------------------------
        # Preferred: label-driven matching (numbers to the LEFT of label in same band)
        # -------------------------
        if labels:
            for lab in labels:
                st = _LABEL_TO_ST[lab["label"]]
                # Horizontal band around the label row
                band_top = lab["cy"] - max(22, lab["h"] * 1.2)
                band_bot = lab["cy"] + max(22, lab["h"] * 1.2)

                # candidates LEFT of label
                cands = [n for n in nums if (band_top <= n["cy"] <= band_bot) and (n["cx"] < lab["x"])]
                if not cands:
                    # Wider tolerance on Y if DPI weird
                    cands = [n for n in nums if (abs(n["cy"] - lab["cy"]) <= max(32, lab["h"] * 1.6)) and (n["cx"] < lab["x"])]
                if not cands:
                    continue

                # Choose closest on X (to the left) with a small confidence bonus
                def score(nw: Dict[str, float]) -> float:
                    dx = lab["x"] - nw["cx"]
                    return dx - (nw["conf"] * 0.4)  # lower is better

                best = min(cands, key=score)
                val = _to_int(best["t"])
                if val:
                    results[st] = max(results.get(st, 0), val)

        # -------------------------
        # Fallback: group numbers into 5 rows (top→bottom map to Myst/Anc/Void/Pri/Sac)
        # -------------------------
        if not results:
            # Group by Y proximity. We merge tokens that are within a vertical gap threshold.
            tokens = sorted(nums, key=lambda n: n["cy"])

            groups: List[List[Dict[str, float]]] = []
            for tok in tokens:
                placed = False
                for g in groups:
                    # Compare to the group's median Y (use first token's cy as seed)
                    gy = sum(t["cy"] for t in g) / len(g)
                    if abs(tok["cy"] - gy) <= max(22, (g[0]["h"] * 1.2)):
                        g.append(tok)
                        placed = True
                        break
                if not placed:
                    groups.append([tok])

            # Reduce each group to a single "best number" by highest confidence / largest width
            def best_in_group(g: List[Dict[str, float]]) -> Dict[str, float]:
                return max(g, key=lambda t: (t["conf"], t["w"]))

            rows = [best_in_group(g) for g in groups]
            # Heuristic: pick the 5 rows most likely to be shard counts (largest width or confidence),
            # then sort by Y (top→bottom).
            rows = sorted(rows, key=lambda t: (t["conf"], t["w"]), reverse=True)[:5]
            rows = sorted(rows, key=lambda t: t["cy"])

            order = [
                ShardType.MYSTERY,
                ShardType.ANCIENT,
                ShardType.VOID,
                ShardType.PRIMAL,
                ShardType.SACRED,
            ]
            for st, row in zip(order, rows):
                val = _to_int(row["t"])
                results[st] = max(results.get(st, 0), val)

        # Fill missing with zeros for consistency
        for st in ShardType:
            results.setdefault(st, 0)

        return results
    except Exception:
        # On any runtime error, fail-soft with {}
        return {}


# ---------- Runtime diagnostics ----------


def ocr_runtime_info() -> Optional[Dict[str, str]]:
    """
    Returns versions for tesseract, pytesseract, and Pillow if available; else None.
    """
    try:
        import pytesseract
        from PIL import Image

        # tesseract --version output (first line)
        try:
            import subprocess

            out = subprocess.check_output(["tesseract", "--version"], stderr=subprocess.STDOUT, text=True)
            first_line = out.splitlines()[0].strip() if out else "tesseract (unknown)"
        except Exception:
            first_line = "tesseract (unavailable)"

        return {
            "tesseract_version": first_line,
            "pytesseract_version": getattr(pytesseract, "__version__", "?"),
            "pillow_version": getattr(Image, "PILLOW_VERSION", None)
            or getattr(Image, "__version__", "?"),
        }
    except Exception:
        return None


def ocr_smoke_test() -> Tuple[bool, Optional[str]]:
    """
    Renders '12345' and OCRs it. Returns (ok, text_read).
    ok=True if digits-only of OCR result equal '12345'.
    """
    try:
        import pytesseract
        from PIL import Image, ImageDraw, ImageOps

        # White background, black text using default bitmap font
        W, H = 240, 80
        img = Image.new("L", (W, H), 255)
        d = ImageDraw.Draw(img)
        text = "12345"
        # Draw in the middle-ish with default font
        d.text((20, 20), text, fill=0)

        # Slight enlarge to help OCR
        img2 = img.resize((W * 2, H * 2))
        img2 = ImageOps.autocontrast(img2)

        cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
        raw = pytesseract.image_to_string(img2, config=cfg) or ""
        digits = re.sub(r"\D+", "", raw)
        return (digits == "12345", raw.strip() or digits or "")
    except Exception:
        return (False, None)
