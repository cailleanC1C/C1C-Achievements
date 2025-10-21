"""Icon locator for the achievements left rail."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

log = logging.getLogger("c1c.achievements.ocr")


@dataclass
class TileHit:
    """Descriptor for a located achievements tile."""

    name: str
    x: int
    y: int
    w: int
    h: int
    score: float


TILE_ORDER: Sequence[str] = ("Mystery", "Ancient", "Void", "Primal", "Sacred")

# Number ROI as % of estimated tile bbox (x%, y%, w%, h%)
NUMBER_ROI: Dict[str, Tuple[int, int, int, int]] = {
    "Mystery": (6, 74, 35, 20),
    "Ancient": (6, 74, 28, 20),
    "Void": (6, 74, 28, 20),
    "Primal": (6, 74, 28, 20),
    "Sacred": (6, 74, 28, 20),
}

# Small global Y offset to sit the ROI directly on the digits
ROI_Y_OFFSET_PCT = 2


def _asset_path(fname: str) -> str:
    here = os.path.dirname(__file__)
    return os.path.abspath(os.path.join(here, "..", "assets", "ocr", "icons", fname))


def load_templates() -> Dict[str, np.ndarray]:
    """
    Load icon templates from disk.

    Missing or unreadable files are logged and skipped.
    """

    files = {
        "Mystery": _asset_path("mystery.png"),
        "Ancient": _asset_path("ancient.png"),
        "Void": _asset_path("void.png"),
        "Primal": _asset_path("primal.png"),
        "Sacred": _asset_path("sacred.png"),
    }
    templates: Dict[str, np.ndarray] = {}
    for name, path in files.items():
        if os.path.exists(path):
            image = cv2.imread(path, cv2.IMREAD_COLOR)
            if image is not None:
                templates[name] = image
                h, w = image.shape[:2]
                log.info("OCR template loaded: %s (%s) size=%sx%s", name, path, w, h)
            else:
                log.warning("OCR template unreadable: %s (%s)", name, path)
        else:
            log.warning("OCR template missing: %s (%s)", name, path)
    return templates


def match_icons(
    full_img: np.ndarray,
    templates: Dict[str, np.ndarray],
    scales: Sequence[float] = (
        0.60,
        0.70,
        0.80,
        0.90,
        1.00,
        1.10,
        1.20,
        1.30,
        1.40,
        1.50,
    ),
    thresh: float = 0.65,
) -> List[TileHit]:
    """Run multi-scale template matching for each icon."""

    hits: List[TileHit] = []
    if not templates:
        return hits

    # Work in grayscale for stable correlation across hue changes and glow
    if full_img.ndim == 3:
        color_code = cv2.COLOR_BGRA2GRAY if full_img.shape[2] == 4 else cv2.COLOR_BGR2GRAY
        hay = cv2.cvtColor(full_img, color_code)
    else:
        hay = full_img.copy()

    for name in TILE_ORDER:
        template = templates.get(name)
        if template is None:
            continue

        # Templates are also normalized to grayscale to avoid color variance issues
        if template.ndim == 3:
            tpl_color = cv2.COLOR_BGRA2GRAY if template.shape[2] == 4 else cv2.COLOR_BGR2GRAY
            tpl_gray = cv2.cvtColor(template, tpl_color)
        else:
            tpl_gray = template

        best: Optional[TileHit] = None
        for scale in scales:
            tw = max(10, int(tpl_gray.shape[1] * scale))
            th = max(10, int(tpl_gray.shape[0] * scale))
            resized = cv2.resize(tpl_gray, (tw, th), interpolation=cv2.INTER_AREA)
            if hay.shape[0] < th or hay.shape[1] < tw:
                continue
            result = cv2.matchTemplate(hay, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val < thresh:
                continue

            x, y = max_loc
            candidate = TileHit(name=name, x=x, y=y, w=tw, h=th, score=float(max_val))
            if best is None or candidate.score > best.score:
                best = candidate

        if best:
            hits.append(best)
        log.info(
            "OCR icon match %s: best=%.3f scale≈%.2f",
            name,
            best.score if best else -1.0,
            (best.w / tpl_gray.shape[1]) if best else -1.0,
        )

    hits.sort(key=lambda hit: hit.y)
    log.info("OCR icon matches: %s", [(hit.name, round(hit.score, 3)) for hit in hits])
    return hits


def match_corners(
    full_img: np.ndarray,
    templates: Dict[str, np.ndarray],
    scales: Sequence[float] = (
        0.60,
        0.70,
        0.80,
        0.90,
        1.00,
        1.10,
        1.20,
        1.30,
        1.40,
        1.50,
    ),
    thresh: float = 0.65,
) -> List[TileHit]:
    """Run template matching using the corner crops supplied by the user."""

    hits: List[TileHit] = []
    if not templates:
        return hits

    # Grayscale matching is more robust for user-supplied corner crops
    if full_img.ndim == 3:
        color_code = cv2.COLOR_BGRA2GRAY if full_img.shape[2] == 4 else cv2.COLOR_BGR2GRAY
        hay = cv2.cvtColor(full_img, color_code)
    else:
        hay = full_img.copy()

    for name in TILE_ORDER:
        template = templates.get(name)
        if template is None:
            continue

        if template.ndim == 3:
            tpl_color = cv2.COLOR_BGRA2GRAY if template.shape[2] == 4 else cv2.COLOR_BGR2GRAY
            tpl_gray = cv2.cvtColor(template, tpl_color)
        else:
            tpl_gray = template

        best: Optional[TileHit] = None
        for scale in scales:
            tw = max(10, int(tpl_gray.shape[1] * scale))
            th = max(10, int(tpl_gray.shape[0] * scale))
            resized = cv2.resize(tpl_gray, (tw, th), interpolation=cv2.INTER_AREA)
            if hay.shape[0] < th or hay.shape[1] < tw:
                continue
            result = cv2.matchTemplate(hay, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val < thresh:
                continue

            x, y = max_loc
            candidate = TileHit(name=name, x=x, y=y, w=tw, h=th, score=float(max_val))
            if best is None or candidate.score > best.score:
                best = candidate

        if best:
            hits.append(best)
        log.info(
            "OCR corner match %s: best=%.3f scale≈%.2f",
            name,
            best.score if best else -1.0,
            (best.w / tpl_gray.shape[1]) if best else -1.0,
        )

    hits.sort(key=lambda hit: hit.y)
    log.info("OCR corner matches: %s", [(hit.name, round(hit.score, 3)) for hit in hits])
    return hits


def tiles_to_number_rois(
    full_img: np.ndarray, hits: Sequence[TileHit]
) -> List[Tuple[str, np.ndarray, Tuple[int, int, int, int]]]:
    """Return cropped number regions for each located tile."""

    height, width = full_img.shape[:2]
    output: List[Tuple[str, np.ndarray, Tuple[int, int, int, int]]] = []
    for hit in hits:
        # estimate tile bbox from icon bbox
        tile_h = int(hit.h * 1.9)
        tile_w = int(hit.w * 2.1)
        tile_x = max(0, hit.x - int(hit.w * 0.25))
        tile_y = max(0, hit.y - int(hit.h * 0.35))
        tile_x2 = min(width, tile_x + tile_w)
        tile_y2 = min(height, tile_y + tile_h)

        rx, ry, rw, rh = NUMBER_ROI.get(hit.name, (6, 74, 30, 20))
        ry += ROI_Y_OFFSET_PCT
        number_x = tile_x + int((rx / 100) * (tile_x2 - tile_x))
        number_y = tile_y + int((ry / 100) * (tile_y2 - tile_y))
        number_w = int((rw / 100) * (tile_x2 - tile_x))
        number_h = int((rh / 100) * (tile_y2 - tile_y))
        number_x2 = min(width, number_x + number_w)
        number_y2 = min(height, number_y + number_h)

        roi = full_img[number_y:number_y2, number_x:number_x2]
        output.append((hit.name, roi, (number_x, number_y, number_x2 - number_x, number_y2 - number_y)))

    return output


def corners_to_number_rois(
    full_img: np.ndarray, hits: Sequence[TileHit]
) -> List[Tuple[str, np.ndarray, Tuple[int, int, int, int]]]:
    """Estimate tile bounds from corner hits and return number ROIs."""

    height, width = full_img.shape[:2]
    output: List[Tuple[str, np.ndarray, Tuple[int, int, int, int]]] = []
    for hit in hits:
        tile_w = int(hit.w * 3.2)
        tile_h = int(hit.h * 1.7)
        tile_x = max(0, hit.x - int(hit.w * 0.10))
        tile_y = max(0, hit.y - int(hit.h * 0.10))
        tile_x2 = min(width, tile_x + tile_w)
        tile_y2 = min(height, tile_y + tile_h)

        rx, ry, rw, rh = NUMBER_ROI.get(hit.name, (6, 74, 30, 20))
        ry += ROI_Y_OFFSET_PCT
        number_x = tile_x + int((rx / 100) * (tile_x2 - tile_x))
        number_y = tile_y + int((ry / 100) * (tile_y2 - tile_y))
        number_w = int((rw / 100) * (tile_x2 - tile_x))
        number_h = int((rh / 100) * (tile_y2 - tile_y))
        number_x2 = min(width, number_x + number_w)
        number_y2 = min(height, number_y + number_h)

        roi = full_img[number_y:number_y2, number_x:number_x2]
        output.append((hit.name, roi, (number_x, number_y, number_x2 - number_x, number_y2 - number_y)))

    return output
