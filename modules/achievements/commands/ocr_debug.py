"""Utilities used by the OCR debug command."""
from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np

from ..locators.left_rail import load_templates, match_icons, tiles_to_number_rois
from ..ocr_pipeline import collect_debug_fields, find_counter_rois_with_boxes


async def build_debug_fields(full_img: np.ndarray) -> List[Tuple[str, str]]:
    """Return embed-friendly fields for the OCR debug command."""

    return await collect_debug_fields(full_img)


def build_left_rail_overlay(full_img: np.ndarray) -> Optional[bytes]:
    """Return a PNG overlay highlighting detected number ROIs (if any)."""

    if full_img is None or full_img.size == 0:
        return None

    rois = find_counter_rois_with_boxes(full_img)
    if rois:
        overlays = rois
    else:
        templates = load_templates()
        hits = match_icons(full_img, templates)
        overlays = tiles_to_number_rois(full_img, hits)

    if not overlays:
        return None

    vis = full_img.copy()
    for name, _roi, (x, y, w, h) in overlays:
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(
            vis,
            name,
            (x, max(20, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    ok, encoded = cv2.imencode(".png", vis)
    if not ok:
        return None
    return encoded.tobytes()


__all__ = [
    "build_debug_fields",
    "build_left_rail_overlay",
]
