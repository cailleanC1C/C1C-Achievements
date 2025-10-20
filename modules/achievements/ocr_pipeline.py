"""Lightweight OCR pipeline for shard achievement counters."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import pytesseract

__all__ = [
    "DEFAULT_CONFIG",
    "BAND_ORDER",
    "OcrBand",
    "preprocess_for_ocr",
    "tesseract_read",
    "find_counter_rois",
    "read_counters",
    "collect_debug_fields",
]

DEFAULT_CONFIG = "--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789."

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

    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

    gray = cv2.GaussianBlur(gray, (3, 3), 0)

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


def find_counter_rois(full_img: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """Split the screenshot into vertical bands for the shard counters."""

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


def read_counters(full_img: np.ndarray) -> Dict[str, Any]:
    """Read all shard counters from the provided screenshot."""

    results: Dict[str, int] = {}
    bands: List[OcrBand] = []

    for name, roi in find_counter_rois(full_img):
        prep = preprocess_for_ocr(roi, band_name=name)
        text = tesseract_read(prep, band_name=name)
        value = text.rstrip(".")
        try:
            parsed = int(value) if value else 0
        except Exception:
            parsed = 0
        results[name] = parsed
        bands.append(
            OcrBand(
                name=name,
                text=text,
                confidence=-1.0,
                metadata={"band_name": name},
            )
        )

    return {"counts": results, "bands": bands}


async def collect_debug_fields(full_img: np.ndarray) -> List[Tuple[str, str]]:
    """Generate embed-friendly fields describing the OCR pass."""

    fields: List[Tuple[str, str]] = []
    for name, roi in find_counter_rois(full_img):
        prep_img = preprocess_for_ocr(roi, band_name=name)
        text = await _tesseract_ocr_async(prep_img, band_name=name)
        note = " (sacred-tuned)" if name.lower().startswith("sacred") else ""
        fields.append((name, f"Raw{note}: `{text or '∅'}`"))
    return fields
