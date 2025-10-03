# cogs/shards/ocr.py
from __future__ import annotations
import io
import re
from typing import Dict, List, Tuple

from .constants import ShardType

# Accept "1,610" / "1.610" / "1 610" etc.
_NUM_RE = re.compile(r"^\d{1,4}(?:[.,\s]\d{3})*$")

ORDER = [
    ShardType.MYSTERY,
    ShardType.ANCIENT,
    ShardType.VOID,
    ShardType.PRIMAL,
    ShardType.SACRED,
]

def _normalize_digits(s: str) -> str:
    # fix common OCR slips: l/İ/I → 1, O/º → 0
    tbl = str.maketrans({
        "l": "1", "I": "1", "İ": "1", "í": "1",
        "O": "0", "o": "0", "º": "0",
    })
    return (s or "").translate(tbl)

def _to_int(num_text: str) -> int:
    s = _normalize_digits(num_text).replace(",", "").replace(".", "").replace(" ", "")
    return int(s) if s.isdigit() else 0

def _scale_if_small(w: int, h: int) -> float:
    # Phone screenshots benefit from upscale before OCR
    if w < 900:
        return 2.0
    if w < 1300:
        return 1.5
    return 1.0

def _encode_png(pil_img) -> bytes:
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue()

def _pick_rows(nums: List[dict]) -> List[dict]:
    """
    Collapse many numeric boxes into at most 5 rows (top→bottom),
    keeping the highest-confidence candidate per row.
    """
    if not nums:
        return []
    nums = sorted(nums, key=lambda n: n["cy"])  # top→bottom
    rows: List[List[dict]] = []
    row_band = max(28, int(sum(n["h"] for n in nums) / max(1, len(nums))))  # dynamic vertical gap

    for n in nums:
        if not rows:
            rows.append([n]); continue
        last_cy = rows[-1][-1]["cy"]
        if abs(n["cy"] - last_cy) > row_band:
            rows.append([n])
        else:
            rows[-1].append(n)

    picked: List[dict] = []
    for group in rows:
        # prefer higher confidence, then wider box (tends to be the count, not noise)
        best = max(group, key=lambda g: (g["conf"], g["w"]))
        picked.append(best)

    # keep first 5 rows
    return picked[:5]

def extract_counts_with_debug(data: bytes) -> Tuple[Dict[ShardType, int], List[Tuple[str, bytes]]]:
    """
    Numbers-only OCR on the LEFT rail. Returns:
      ( {ShardType:int}, [("roi_gray.png", bytes), ("roi_bin.png", bytes)] )
    """
    try:
        import pytesseract
        from pytesseract import Output
        from PIL import Image, ImageOps, ImageFilter
    except Exception:
        # OCR stack missing: fail-safe
        return ({st: 0 for st in ORDER}, [])

    # --- load & normalize orientation ---
    base = Image.open(io.BytesIO(data))
    base = ImageOps.exif_transpose(base)

    # --- upscale small sources ---
    scale = _scale_if_small(base.width, base.height)
    if scale != 1.0:
        base = base.resize((int(base.width * scale), int(base.height * scale)))

    W, H = base.width, base.height

    # -------------------------
    # ROI: left rail with shard icons + counts
    # Keep it tight so we don't catch the right-side capacity numbers.
    # Start conservative; we can adjust if needed.
    # -------------------------
    roi_x2 = int(W * 0.33)  # ~33% of width from left
    roi = base.crop((0, 0, roi_x2, H))

    # Preprocess: grayscale → autocontrast → unsharp → binarize
    roi_gray = ImageOps.grayscale(roi)
    roi_gray = ImageOps.autocontrast(roi_gray)
    roi_sharp = roi_gray.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))

    # Binarize; 120 is a good starting point for your screenshots
    threshold = 120
    roi_bin = roi_sharp.point(lambda p: 255 if p > threshold else 0)

    # Try a few PSMs for robustness
    psm_list = [7, 6, 11]
    nums: List[dict] = []

    for psm in psm_list:
        cfg = (
            f"--oem 3 --psm {psm} "
            "-c tessedit_char_whitelist=0123456789., "
            "-c preserve_interword_spaces=1 "
            "-c classify_bln_numeric_mode=1"
        )
        dd = pytesseract.image_to_data(roi_bin, output_type=Output.DICT, config=cfg)

        for i in range(len(dd["text"])):
            raw = (dd["text"][i] or "").strip()
            if not raw:
                continue
            t = _normalize_digits(raw)
            t_for_match = t.replace("\u00A0", " ")  # NBSP
            if not (_NUM_RE.match(t_for_match) or t_for_match.isdigit()):
                continue
            try:
                conf = float(dd["conf"][i])
            except Exception:
                conf = -1.0
            if conf < 30:
                continue
            x = int(dd["left"][i]); y = int(dd["top"][i])
            w = int(dd["width"][i]); h = int(dd["height"][i])
            nums.append({
                "t": t, "x": x, "y": y, "w": w, "h": h,
                "cx": x + w / 2, "cy": y + h / 2,
                "conf": conf,
            })

        # If we already have a decent set, break early
        if len(nums) >= 5:
            break

    # Collapse into rows and map to shard order
    rows = _pick_rows(nums)
    counts = [ _to_int(n["t"]) for n in rows ]
    # pad/trim to exactly 5
    while len(counts) < 5:
        counts.append(0)
    counts = counts[:5]

    result: Dict[ShardType, int] = { ORDER[i]: counts[i] for i in range(5) }

    # Debug images to inspect what OCR saw
    debug_imgs: List[Tuple[str, bytes]] = [
        ("roi_gray.png", _encode_png(roi_gray)),
        ("roi_bin.png",  _encode_png(roi_bin)),
    ]
    return result, debug_imgs

def extract_counts_from_image_bytes(data: bytes) -> Dict[ShardType, int]:
    """
    Backwards-compatible wrapper used by existing code paths.
    """
    counts, _ = extract_counts_with_debug(data)
    return counts
