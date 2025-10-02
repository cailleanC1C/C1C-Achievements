"""Prefix guidance helpers for CoreOps messaging."""
from __future__ import annotations

from core.prefix import PREFIX_LABELS, SCOPED_PREFIXES

__all__ = ("format_prefix_picker",)


def format_prefix_picker(command_word: str) -> str:
    """Render guidance when someone should choose a bot-specific prefix."""
    keyword = (command_word or "this command").strip() or "this command"
    bullets = "\n".join(
        f"• `{prefix} {keyword}` — {PREFIX_LABELS[prefix]}" for prefix in SCOPED_PREFIXES
    )
    return f"For which bot do you want to run **{keyword}**?\n{bullets}"
