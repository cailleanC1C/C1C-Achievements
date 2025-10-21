"""Runtime configuration helpers shared across bots."""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["configure_feature_toggles", "get_feature_toggles", "is_enabled"]

_FEATURE_TOGGLE_DEFAULTS: dict[str, bool] = {}
_FEATURE_TOGGLE_OVERRIDES: dict[str, bool] = {}
_FEATURE_TOGGLES: dict[str, bool] = {}


def _to_bool(value: Any) -> bool:
    """Best-effort coercion of spreadsheet/env values to booleans."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y", "on", "enabled"}


def _normalize(items: Mapping[str, Any]) -> dict[str, bool]:
    normalized: dict[str, bool] = {}
    for raw_key, raw_value in items.items():
        if raw_key is None:
            continue
        key = str(raw_key).strip()
        if not key:
            continue
        normalized[key] = _to_bool(raw_value)
    return normalized


def configure_feature_toggles(*, defaults: Mapping[str, Any] | None = None, overrides: Mapping[str, Any] | None = None) -> None:
    """Configure feature toggle defaults and overrides.

    Passing ``defaults`` replaces the defaults map. Passing ``overrides`` updates the
    active sheet-sourced overrides. Either argument is optional; when omitted the
    previous values remain in effect. After merging defaults and overrides the
    resulting toggle map is stored for access via :func:`get_feature_toggles` and
    :func:`is_enabled`.
    """
    global _FEATURE_TOGGLE_DEFAULTS, _FEATURE_TOGGLE_OVERRIDES, _FEATURE_TOGGLES

    if defaults is not None:
        _FEATURE_TOGGLE_DEFAULTS = _normalize(defaults)
    if overrides is not None:
        _FEATURE_TOGGLE_OVERRIDES = _normalize(overrides)

    merged: dict[str, bool] = dict(_FEATURE_TOGGLE_DEFAULTS)
    merged.update(_FEATURE_TOGGLE_OVERRIDES)
    _FEATURE_TOGGLES = merged


def get_feature_toggles() -> dict[str, bool]:
    """Return a copy of the merged feature toggle map."""
    return dict(_FEATURE_TOGGLES)


def is_enabled(name: str) -> bool:
    """Return ``True`` when the given feature toggle is enabled."""
    key = (name or "").strip()
    if not key:
        return False
    return _FEATURE_TOGGLES.get(key, False)
