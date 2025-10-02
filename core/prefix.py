"""Prefix helpers for the C1C Achievements bot."""
from __future__ import annotations

from typing import Any, List, Sequence, Tuple

SCOPED_PREFIXES: Tuple[str, ...] = ("!sc", "!rem", "!wc", "!mm")
GLOBAL_PREFIX: str = "!"
ALL_PREFIXES: Tuple[str, ...] = SCOPED_PREFIXES + (GLOBAL_PREFIX,)
PREFIX_LABELS = {
    "!sc": "Scribe",
    "!rem": "Reminder",
    "!wc": "Welcome Crew",
    "!mm": "Matchmaker",
}


def get_prefix(_bot: Any, message: Any) -> Sequence[str]:
    """Return the runtime prefix list for discord.py."""

    content = getattr(message, "content", "") or ""
    matched_prefixes: List[str] = [
        prefix for prefix in SCOPED_PREFIXES if content.startswith(prefix)
    ]
    remaining_prefixes: List[str] = [
        prefix for prefix in SCOPED_PREFIXES if prefix not in matched_prefixes
    ]

    return [*matched_prefixes, *remaining_prefixes, GLOBAL_PREFIX]


def is_scoped_prefix(prefix: str) -> bool:
    """Return True if the prefix is one of the scoped CoreOps prefixes."""
    return prefix.lower() in {p.lower() for p in SCOPED_PREFIXES}
