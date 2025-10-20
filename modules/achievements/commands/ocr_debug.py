"""Utilities used by the OCR debug command."""
from __future__ import annotations

from typing import List, Tuple

import numpy as np

from ..ocr_pipeline import collect_debug_fields


async def build_debug_fields(full_img: np.ndarray) -> List[Tuple[str, str]]:
    """Return embed-friendly fields for the OCR debug command."""

    return await collect_debug_fields(full_img)
