# cogs/shards/ocr.py
from __future__ import annotations

import io
import re
import subprocess
from dataclasses import dataclass, replace
from typing import Dict, List, Tuple, Optional

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

_LABEL_TO_ST = {
    "mystery": ShardType.MYSTERY,
    "ancient": ShardType.ANCIENT,
    "void": ShardType.VOID,
    "primal": ShardType.PRIMAL,
    "sacred": ShardType.SACRED,
}


def _label_key(label: str) -> str | None:
    cleaned = re.sub(r"[^a-z]", "", label.lower())
    for candidate in (cleaned, cleaned.rstrip("s")):
        for key in _LABEL_TO_ST:
            if candidate.startswith(key):
                return key
    return None


@dataclass
class _OcrToken:
    left: int
    top: int
    width: int
    height: int
    conf: float
    text: str
    source: str = ""

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def cx(self) -> int:
        return self.left + self.width // 2

    @property
    def cy(self) -> int:
        return self.top + self.height // 2


def _rounded_token_key(tok: _OcrToken, step: int = 4) -> Tuple[int, int, int, int, str]:
    def _r(v: int) -> int:
        return int(round(v / step) * step)

    return (_r(tok.left), _r(tok.top), _r(tok.width), _r(tok.height), tok.text)


def _extract_oem_psm(cfg: str) -> Tuple[int, int]:
    oem = -1
    psm = -1
    try:
        m = re.search(r"--oem\s+(\d)", cfg)
        if m:
            oem = int(m.group(1))
    except Exception:
        pass
    try:
        m = re.search(r"--psm\s+(\d+)", cfg)
        if m:
            psm = int(m.group(1))
    except Exception:
        pass
    return oem, psm


def _summarize_config(cfg: str) -> str:
    oem, psm = _extract_oem_psm(cfg)
    parts = []
    if oem >= 0:
        parts.append(f"--oem {oem}")
    if psm >= 0:
        parts.append(f"--psm {psm}")
    return " ".join(parts) or cfg.strip()


def _otsu_threshold(gray: "Image.Image") -> int:
    hist = gray.histogram()
    total = sum(hist)
    sum_total = 0.0
    for i, h in enumerate(hist):
        sum_total += i * h

    sumB = 0.0
    wB = 0.0
    max_var = -1.0
    threshold = 127
    for i, h in enumerate(hist):
        wB += h
        if wB == 0:
            continue
        wF = total - wB
        if wF == 0:
            break
        sumB += i * h
        mB = sumB / wB
        mF = (sum_total - sumB) / wF
        between = wB * wF * (mB - mF) ** 2
        if between > max_var:
            max_var = between
            threshold = i
    return threshold


def _parse_source_meta(source: str) -> Tuple[str, str]:
    cfg = source
    processed = ""
    for part in (source or "").split("|"):
        if part.startswith("cfg="):
            cfg = part[4:]
        elif part.startswith("img="):
            processed = part[4:]
    return cfg, processed


@dataclass
class BandDebugImage:
    shard: ShardType
    band_index: int
    ratio: float
    aggressive: bool
    width: int
    height: int
    raw_bytes: bytes
    processed_bytes: bytes
    processed_label: str
    oem: int
    psm: int
    config_summary: str
    text: str
    conf: float


@dataclass
class OcrDebugBundle:
    counts: Dict[ShardType, int]
    score: int
    ratio: float
    bands: List[BandDebugImage]


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
        try:
            proc = subprocess.run(
                ["tesseract", "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            lines = (proc.stdout or proc.stderr or "").splitlines()
            cli_ver = lines[0].strip() if lines else "unknown"
        except Exception:
            cli_ver = "unknown"
        try:
            langs = sorted(set(pytesseract.get_languages(config="") or []))
            lang_str = ", ".join(langs)
        except Exception:
            lang_str = ""
        return {
            "tesseract_version": tver,
            "tesseract_cli_version": cli_ver,
            "pytesseract_version": getattr(pytesseract, "__version__", "unknown"),
            "pillow_version": getattr(Image, "__version__", "unknown"),
            "tesseract_languages": lang_str,
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
        ratios = (0.38, 0.42, 0.46)
        best_counts: Dict[ShardType, int] = {}
        best_score = -1

        for r in ratios:
            roi = _left_rail_crop(base, r)
            counts, score, _ = _read_counts_from_roi(roi, timeout_sec=6)
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

        ratios = (0.38, 0.42, 0.46)

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
            counts, score, _ = _read_counts_from_roi(roi, timeout_sec=timeout_sec)
            if score > best_score:
                best_counts, best_score = counts, score

        for st in ShardType:
            best_counts.setdefault(st, 0)

        return (best_counts, dbg)
    except Exception:
        return ({}, [])


# ---------------------------
# Debug helpers
# ---------------------------

def collect_debug_bundle(data: bytes, timeout_sec: int = 6) -> Optional[OcrDebugBundle]:
    if pytesseract is None or Image is None or ImageOps is None:
        return None

    try:
        base = Image.open(io.BytesIO(data))
        base = ImageOps.exif_transpose(base)

        scale = _scale_if_small(base.width, base.height)
        if scale != 1.0:
            base = base.resize((int(base.width * scale), int(base.height * scale)))

        ratios = (0.38, 0.42, 0.46)
        best_counts: Dict[ShardType, int] = {}
        best_score = -1
        best_ratio = ratios[0]
        best_debug: List[BandDebugImage] = []

        for r in ratios:
            roi = _left_rail_crop(base, r)
            counts, score, debug_entries = _read_counts_from_roi(
                roi,
                timeout_sec=timeout_sec,
                collect_debug=True,
                ratio=r,
            )
            if score > best_score:
                best_counts = counts
                best_score = score
                best_ratio = r
                best_debug = debug_entries

        for st in ShardType:
            best_counts.setdefault(st, 0)

        return OcrDebugBundle(
            counts=best_counts,
            score=best_score,
            ratio=best_ratio,
            bands=best_debug,
        )
    except Exception:
        return None


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


def _preprocess_roi_strong(roi: "Image.Image") -> Tuple["Image.Image", "Image.Image"]:
    """Aggressive preprocessing (adaptive threshold) used for fallback passes."""
    gray = ImageOps.grayscale(roi)
    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1.2, percent=160, threshold=2))
    thresh = _otsu_threshold(gray)
    bin_img = gray.point(lambda p: 255 if p > thresh else 0)
    bin_img = bin_img.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
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


def _merge_band_tokens(tokens: List[_OcrToken]) -> List[_OcrToken]:
    if not tokens:
        return []

    merged: List[_OcrToken] = []
    for tok in sorted(tokens, key=lambda t: t.left):
        if not merged:
            merged.append(tok)
            continue

        prev = merged[-1]
        gap = tok.left - prev.right
        overlap = min(prev.right, tok.right) - max(prev.left, tok.left)
        min_width = max(1, min(prev.width, tok.width))

        if gap < 0 and overlap >= int(0.6 * min_width):
            best, other = (tok, prev) if _score_band_token(tok.text, tok.conf) > _score_band_token(prev.text, prev.conf) else (prev, tok)
            new_conf = max(prev.conf, tok.conf)
            merged[-1] = replace(best, conf=new_conf)
            continue

        max_gap = max(2, int(0.5 * min_width))
        if gap <= max_gap:
            new_left = min(prev.left, tok.left)
            new_top = min(prev.top, tok.top)
            new_right = max(prev.right, tok.right)
            new_bottom = max(prev.bottom, tok.bottom)
            merged[-1] = _OcrToken(
                left=new_left,
                top=new_top,
                width=new_right - new_left,
                height=new_bottom - new_top,
                conf=min(prev.conf, tok.conf),
                text=prev.text + tok.text,
                source=prev.source or tok.source,
            )
            continue

        merged.append(tok)

    return merged


def _run_psm7_band_pass(
    sub_img_bin: "Image.Image",
    sub_img_gray: "Image.Image",
    timeout_sec: int,
    aggressive: bool = False,
) -> Tuple[str, float, str] | None:
    """Run the tighter per-band OCR pass and return the best (text, conf, cfg)."""
    picks: List[Tuple[str, float, str]] = []
    if aggressive:
        cfgs = [
            "--oem 1 --psm 8 -c tessedit_char_whitelist=0123456789 -c classify_bln_numeric_mode=1",
            "--oem 1 --psm 10 -c tessedit_char_whitelist=0123456789 -c classify_bln_numeric_mode=1",
        ]
    else:
        cfgs = [
            "--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789., -c classify_bln_numeric_mode=1",
        ]

    for label, sub_img in (("bin", sub_img_bin), ("gray", sub_img_gray)):
        for cfg in cfgs:
            try:
                dd2 = pytesseract.image_to_data(
                    sub_img,
                    output_type=Output.DICT,
                    config=cfg,
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
                    picks.append(
                        (
                            t2,
                            conf2,
                            f"mode={'fallback' if aggressive else 'primary'}|img={label}|cfg={cfg}|micro=1",
                        )
                    )

    if not picks:
        return None

    return max(picks, key=lambda p: _score_band_token(p[0], p[1]))


def _read_counts_from_roi(
    roi,
    timeout_sec: int = 6,
    *,
    collect_debug: bool = False,
    ratio: float = 0.0,
) -> Tuple[Dict[ShardType, int], int, List[BandDebugImage]]:
    """OCR the ROI and split vertically into 5 bands."""
    primary = _read_counts_from_roi_impl(
        roi,
        timeout_sec=timeout_sec,
        aggressive=False,
        collect_debug=collect_debug,
        ratio=ratio,
    )
    counts, score, debug_primary = primary
    if score > 0:
        return counts, score, debug_primary if collect_debug else []

    fallback = _read_counts_from_roi_impl(
        roi,
        timeout_sec=timeout_sec,
        aggressive=True,
        collect_debug=collect_debug,
        ratio=ratio,
    )
    f_counts, f_score, debug_fallback = fallback
    if f_score > score:
        return f_counts, f_score, debug_fallback if collect_debug else []
    return counts, score, debug_primary if collect_debug else []


def _read_counts_from_roi_impl(
    roi,
    *,
    timeout_sec: int,
    aggressive: bool,
    collect_debug: bool,
    ratio: float,
) -> Tuple[Dict[ShardType, int], int, List[BandDebugImage]]:
    if aggressive:
        gray, bin_img = _preprocess_roi_strong(roi)
        cfgs = [
            "--oem 1 --psm 8 -c tessedit_char_whitelist=0123456789., -c preserve_interword_spaces=1 -c classify_bln_numeric_mode=1",
            "--oem 1 --psm 10 -c tessedit_char_whitelist=0123456789 -c classify_bln_numeric_mode=1",
        ]
    else:
        gray, bin_img = _preprocess_roi(roi)
        cfgs = [
            "--oem 3 --psm 6  -c tessedit_char_whitelist=0123456789., -c preserve_interword_spaces=1 -c classify_bln_numeric_mode=1",
            "--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789., -c preserve_interword_spaces=1 -c classify_bln_numeric_mode=1",
        ]

    candidates: List[Tuple[str, "Image.Image"]] = [("bin", bin_img)]
    try:
        candidates.append(("bin_inv", ImageOps.invert(bin_img)))
    except Exception:
        pass
    candidates.append(("gray", gray))

    token_map: Dict[Tuple[int, int, int, int, str], _OcrToken] = {}
    W, H = bin_img.size
    left_frac = 0.60
    max_x = int(W * left_frac)

    for img_label, img in candidates:
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
                token = _OcrToken(
                    left=x,
                    top=y,
                    width=w,
                    height=h,
                    conf=conf,
                    text=txt,
                    source=f"mode={'fallback' if aggressive else 'primary'}|img={img_label}|cfg={cfg}",
                )
                key = _rounded_token_key(token)
                prev = token_map.get(key)
                if prev is None or conf > prev.conf:
                    token_map[key] = token

        if len(token_map) >= 8:
            break

    counts_by_band: List[int] = []
    debug_entries: List[BandDebugImage] = []
    band_h = H / 5.0
    tokens = list(token_map.values())
    order = [ShardType.MYSTERY, ShardType.ANCIENT, ShardType.VOID, ShardType.PRIMAL, ShardType.SACRED]

    for band in range(5):
        y0 = band * band_h
        y1 = (band + 1) * band_h
        cands = [tok for tok in tokens if y0 <= tok.cy < y1]
        cands = _merge_band_tokens(cands)
        best_token: Optional[_OcrToken] = None
        if cands:
            best_token = max(cands, key=lambda t: _score_band_token(t.text, t.conf))

        main_pick: Optional[Tuple[str, float, str]] = None
        if best_token is not None:
            main_pick = (best_token.text, best_token.conf, best_token.source)

        micro_pick: Optional[Tuple[str, float, str]] = None
        bx0, bx1 = 0, max_x
        by0 = int(y0 + band_h * 0.15)
        by1 = int(y0 + band_h * 0.85)
        sub = None
        sub_gray = None
        sub_bin = None
        try:
            sub = roi.crop((bx0, by0, bx1, by1))
            if aggressive:
                sub_gray, sub_bin = _preprocess_roi_strong(sub)
            else:
                sub_gray, sub_bin = _preprocess_roi(sub)
            micro_pick = _run_psm7_band_pass(sub_bin, sub_gray, timeout_sec, aggressive=aggressive)
        except Exception:
            micro_pick = None

        best_pick = main_pick
        if _score_band_token(*(micro_pick or ("", -1.0))) > _score_band_token(*(best_pick or ("", -1.0))):
            best_pick = micro_pick

        if best_pick is None:
            counts_by_band.append(0)
        else:
            counts_by_band.append(_parse_num_token(best_pick[0]))

        if collect_debug:
            cfg_str = ""
            processed_label = ""
            if best_pick is not None:
                cfg_str, processed_label = _parse_source_meta(best_pick[2])
            else:
                cfg_str = ""
                processed_label = "bin"
            if sub is None:
                sub = roi.crop((bx0, by0, bx1, by1))
                if aggressive:
                    sub_gray, sub_bin = _preprocess_roi_strong(sub)
                else:
                    sub_gray, sub_bin = _preprocess_roi(sub)
            processed_img = sub_bin if (processed_label or "bin").startswith("bin") else sub_gray
            processed_img = processed_img or sub_bin or sub_gray
            raw_bytes = _img_to_png_bytes(sub) if sub else b""
            processed_bytes = _img_to_png_bytes(processed_img) if processed_img else b""
            oem, psm = _extract_oem_psm(cfg_str)
            debug_entries.append(
                BandDebugImage(
                    shard=order[band],
                    band_index=band,
                    ratio=ratio,
                    aggressive=aggressive,
                    width=sub.width if sub else 0,
                    height=sub.height if sub else 0,
                    raw_bytes=raw_bytes,
                    processed_bytes=processed_bytes,
                    processed_label=(processed_label or "bin"),
                    oem=oem,
                    psm=psm,
                    config_summary=_summarize_config(cfg_str) if cfg_str else "",
                    text=best_pick[0] if best_pick else "",
                    conf=best_pick[1] if best_pick else -1.0,
                )
            )

    counts: Dict[ShardType, int] = {}
    for st, val in zip(order, counts_by_band):
        counts[st] = max(0, int(val))

    score = sum(1 for v in counts_by_band if v > 0)
    return counts, score, debug_entries


def _img_to_png_bytes(img: "Image.Image") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
