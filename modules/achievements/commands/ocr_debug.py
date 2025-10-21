"""Utilities used by the OCR debug command."""
from __future__ import annotations

from typing import List, Optional, Tuple

import logging

import cv2
import numpy as np

from .. import ocr_pipeline
from ..locators.left_rail import (
    corners_to_number_rois,
    load_templates,
    match_corners,
    match_icons,
    tiles_to_number_rois,
)
from ..ocr_pipeline import collect_debug_fields, find_counter_rois_with_boxes

log = logging.getLogger("c1c-claims")


async def build_debug_fields(full_img: np.ndarray) -> List[Tuple[str, str]]:
    """Return embed-friendly fields for the OCR debug command."""

    return await collect_debug_fields(full_img)


def build_left_rail_overlay(full_img: np.ndarray) -> Optional[bytes]:
    """Return a PNG overlay highlighting detected number ROIs (always attaches)."""

    if full_img is None or full_img.size == 0:
        return None

    overlays = find_counter_rois_with_boxes(full_img)
    locator_mode = "template" if overlays else "none"
    icon_count = len(getattr(ocr_pipeline, "_TEMPLATE_CACHE", {}) or {})
    if icon_count == 0 and overlays:
        icon_count = len({name for name, *_ in overlays})

    if not overlays:
        templates = load_templates()
        icon_count = len(templates)
        hits = match_icons(full_img, templates)
        overlays = tiles_to_number_rois(full_img, hits) if hits else []
        if overlays:
            locator_mode = "icon"
        else:
            corner_hits = match_corners(full_img, templates)
            overlays = corners_to_number_rois(full_img, corner_hits) if corner_hits else []
            locator_mode = "corner" if overlays else "none"

    log.info("[ocrdebug] locator used: %s | icons=%d", locator_mode, icon_count)

    vis = full_img.copy()
    if overlays:
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
    else:
        cv2.putText(
            vis,
            f"no matches (mode={locator_mode}, icons={icon_count})",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 255),
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
