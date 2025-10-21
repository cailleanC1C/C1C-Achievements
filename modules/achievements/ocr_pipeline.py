"""Lightweight OCR pipeline for shard achievement counters."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import pytesseract

log = logging.getLogger("c1c-claims")

from .locators.left_rail import (
    corners_to_number_rois,
    load_templates,
    match_corners,
    match_icons,
    tiles_to_number_rois,
)

__all__ = [
    "DEFAULT_CONFIG",
    "BAND_ORDER",
    "OcrBand",
    "preprocess_for_ocr",
    "tesseract_read",
    "find_counter_rois",
    "find_counter_rois_with_boxes",
    "read_counters",
    "collect_debug_fields",
]

DEFAULT_CONFIG = "--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789."
CONF_FLOOR = 35  # minimum confidence for a digit fragment to be trusted

# Order of shard counters as they appear in the in-game UI from top to bottom.
BAND_ORDER: Tuple[str, ...] = ("Mystery", "Ancient", "Void", "Primal", "Sacred")

_NUM_RE = re.compile(r"^\d+(?:[.,]\d+)?$")


def _looks_like_number(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    # Allow trailing periods produced by the whitelist configuration.
    cleaned = cleaned.rstrip(".")
    if not cleaned:
        return False
    return bool(_NUM_RE.match(cleaned))


def _prep_bin(img_np: np.ndarray) -> np.ndarray:
    """Binarise a ROI for OCR (white digits on a dark background)."""

    if img_np is None or img_np.size == 0:
        raise ValueError("`img_np` must be a non-empty ndarray")

    if img_np.ndim == 3:
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_np

    gray = cv2.medianBlur(gray, 3)
    return cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        9,
    )


def _lenient_digits(bin_or_gray: np.ndarray) -> str:
    """Run a relaxed OCR pass to rescue digits filtered out by confidence checks."""

    if bin_or_gray is None or bin_or_gray.size == 0:
        return ""

    config = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789,"
    try:
        raw = pytesseract.image_to_string(bin_or_gray, lang="eng", config=config) or ""
    except Exception:
        return ""

    raw = raw.replace(",", "")
    return re.sub(r"\D+", "", raw)


@dataclass(slots=True)
class OcrBand:
    """Result of OCR for a single shard band."""

    name: str
    text: str
    confidence: float
    metadata: Dict[str, Any]


def preprocess_for_ocr(img: np.ndarray, band_name: Optional[str] = None) -> np.ndarray:
    """Convert a color ROI into a binarised image suitable for OCR."""

    if img is None or img.size == 0:
        raise ValueError("`img` must be a non-empty ndarray")

    if len(img.shape) == 2:
        color = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    else:
        color = img

    upscaled = cv2.resize(color, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
    gray = cv2.convertScaleAbs(gray, alpha=1.35, beta=10)

    block, C = 19, 2
    if band_name == "Sacred":
        block, C = 23, 3
    bw = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block,
        C,
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=1)
    if band_name == "Sacred":
        k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2))
        bw = cv2.dilate(bw, k_v, iterations=1)
    return bw


def tesseract_read(
    img_bw: np.ndarray,
    config: str = DEFAULT_CONFIG,
    band_name: Optional[str] = None,
) -> str:
    """Run Tesseract on a preprocessed image and normalise the result."""

    if img_bw is None or img_bw.size == 0:
        return ""

    try:
        text = pytesseract.image_to_string(img_bw, config=config).strip()
    except Exception:
        return ""

    if not _looks_like_number(text):
        fallback_cfg = "--oem 1 --psm 8 -c tessedit_char_whitelist=0123456789."
        try:
            text = pytesseract.image_to_string(img_bw, config=fallback_cfg).strip()
        except Exception:
            text = ""

    if not _looks_like_number(text) and band_name == "Sacred":
        single_cfg = "--oem 1 --psm 10 -c tessedit_char_whitelist=0123456789"
        try:
            text = pytesseract.image_to_string(img_bw, config=single_cfg).strip()
        except Exception:
            text = ""

    return text


async def _tesseract_ocr_async(img_bw: np.ndarray, band_name: Optional[str] = None) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, tesseract_read, img_bw, DEFAULT_CONFIG, band_name)


def normalize_count(raw: str) -> Optional[int]:
    """Normalise OCR output (strip punctuation / whitespace) into an int."""

    text = (raw or "").strip().rstrip(".")
    if not text:
        return None

    digits = re.sub(r"[\s,\.]", "", text)
    if not digits.isdigit():
        return None
    try:
        return int(digits)
    except Exception:
        return None


_TEMPLATE_CACHE: Optional[Dict[str, np.ndarray]] = None


def _legacy_find_counter_rois(full_img: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """Fallback ROI splitter using equal vertical bands (legacy behaviour)."""

    if full_img is None or full_img.size == 0:
        return []

    height, width = full_img.shape[:2]
    if height <= 0 or width <= 0:
        return []

    band_height = max(height // len(BAND_ORDER), 1)
    rois: List[Tuple[str, np.ndarray]] = []
    y0 = 0
    for idx, name in enumerate(BAND_ORDER):
        y1 = height if idx == len(BAND_ORDER) - 1 else min(height, y0 + band_height)
        roi = full_img[y0:y1, :]
        rois.append((name, roi))
        y0 = y1
    return rois


def _template_rois_with_boxes(full_img: np.ndarray) -> List[Tuple[str, np.ndarray, Tuple[int, int, int, int]]]:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        _TEMPLATE_CACHE = load_templates()

    templates = _TEMPLATE_CACHE or {}
    icon_hits = match_icons(full_img, templates)
    rois = tiles_to_number_rois(full_img, icon_hits) if icon_hits else []
    if not rois:
        corner_hits = match_corners(full_img, templates)
        rois = corners_to_number_rois(full_img, corner_hits) if corner_hits else []
    return rois


def find_counter_rois_with_boxes(full_img: np.ndarray) -> List[Tuple[str, np.ndarray, Tuple[int, int, int, int]]]:
    """Return template-derived ROIs along with their bounding boxes when available."""

    rois = _template_rois_with_boxes(full_img)
    if len(rois) >= 3:
        return rois
    return []


def find_counter_rois(full_img: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """Return ROIs for each shard counter (template-based with legacy fallback)."""

    template_rois = _template_rois_with_boxes(full_img)
    if len(template_rois) >= 3:
        return [(name, roi) for name, roi, _ in template_rois]

    return _legacy_find_counter_rois(full_img)


def _read_int(name: str, roi_np: np.ndarray) -> Tuple[int, float, str]:
    """Read a numeric ROI and return value, mean confidence and raw text."""

    if roi_np is None or roi_np.size == 0:
        return 0, 0.0, ""

    try:
        binimg = _prep_bin(roi_np)
    except Exception:
        return 0, 0.0, ""

    config = "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789,"
    try:
        data = pytesseract.image_to_data(
            binimg,
            lang="eng",
            config=config,
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return 0, 0.0, ""

    texts: List[str] = []
    confs: List[float] = []
    all_texts: List[str] = []
    all_confs: List[float] = []

    for text, conf in zip(data.get("text", []), data.get("conf", [])):
        if not text:
            continue
        cleaned = text.strip()
        if not cleaned:
            continue
        try:
            score = float(conf)
        except Exception:
            score = -1.0

        all_texts.append(cleaned)
        all_confs.append(score)

        if score < CONF_FLOOR:
            continue

        texts.append(cleaned)
        confs.append(score)

    strict_raw = "".join(texts)
    strict_raw = strict_raw.replace(" ", "").replace(",", "")

    kept = len(texts)
    total = len(all_texts)

    cand_a = strict_raw
    conf_a = float(np.mean(confs)) if confs else 0.0

    cand_b = ""
    conf_b = 0.0

    if total > 0 and kept < total:
        cand_b = _lenient_digits(binimg)
        conf_b = float(np.mean([c for c in all_confs if c >= 0])) if all_confs else 0.0
        log.info(
            "[ocr] %s: lenient fallback considered (kept=%d/%d, strict='%s', loose='%s')",
            name,
            kept,
            total,
            cand_a,
            cand_b,
        )

    def _score(raw: str, confidence: float) -> Tuple[int, float]:
        return len(raw or ""), confidence

    best_raw = cand_a
    best_conf = conf_a

    if cand_b and _score(cand_b, conf_b) > _score(cand_a, conf_a):
        best_raw = cand_b
        best_conf = conf_b
        log.info(
            "[ocr] %s: using lenient result '%s' over strict '%s'", name, best_raw, cand_a
        )

    value = int(best_raw) if best_raw.isdigit() else 0
    return value, best_conf, best_raw


def _read_band(name: str, roi: np.ndarray) -> Tuple[int, float, str, Dict[str, Any]]:
    """Read a band ROI, applying confidence filtering and legacy fallbacks."""

    value, mean_conf, raw = _read_int(name, roi)
    text = raw
    confidence = mean_conf
    metadata: Dict[str, Any] = {
        "band_name": name,
        "reader": "data",
        "data_raw": raw,
        "data_conf": mean_conf,
    }

    if value == 0 and not raw:
        try:
            prep = preprocess_for_ocr(roi, band_name=name)
            fallback_text = tesseract_read(prep, band_name=name)
        except Exception:
            fallback_text = ""

        metadata["legacy_raw"] = fallback_text
        parsed = normalize_count(fallback_text)
        if parsed is not None:
            value = parsed
            text = fallback_text
            confidence = -1.0
            metadata["reader"] = "legacy"

    metadata["value"] = value
    metadata["text"] = text
    return value, confidence, text, metadata


def read_counters(full_img: np.ndarray) -> Dict[str, Any]:
    """Read all shard counters from the provided screenshot."""

    results: Dict[str, int] = {}
    bands: List[OcrBand] = []

    for name, roi in find_counter_rois(full_img):
        value, confidence, text, metadata = _read_band(name, roi)
        results[name] = int(value)
        bands.append(
            OcrBand(
                name=name,
                text=text or "",
                confidence=confidence,
                metadata=metadata,
            )
        )

    return {"counts": results, "bands": bands}


async def collect_debug_fields(full_img: np.ndarray) -> List[Tuple[str, str]]:
    """Generate embed-friendly fields describing the OCR pass."""

    fields: List[Tuple[str, str]] = []
    loop = asyncio.get_running_loop()
    for name, roi in find_counter_rois(full_img):
        _, confidence, text, metadata = await loop.run_in_executor(
            None, _read_band, name, roi
        )
        reader = metadata.get("reader", "data")
        display = text or "∅"
        if reader == "legacy":
            data_raw = metadata.get("data_raw") or "∅"
            data_conf = metadata.get("data_conf", 0.0)
            extras: List[str] = []
            if data_raw and data_raw != "∅":
                extras.append(f"data `{data_raw}`")
            if data_conf > 0:
                extras.append(f"μ={data_conf:.1f}")
            extra = f" ({', '.join(extras)})" if extras else ""
            fields.append((name, f"Legacy: `{display}`{extra}"))
        else:
            conf_note = f" μ={confidence:.1f}" if confidence > 0 else ""
            fields.append((name, f"Digits{conf_note}: `{display}`"))
    return fields
