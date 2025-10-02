"""Prefix helpers for the C1C Achievements bot."""
from __future__ import annotations

from typing import Any, Sequence, Tuple

SCOPED_PREFIXES: Tuple[str, ...] = ("!sc", "!rem", "!wc", "!mm")
GLOBAL_PREFIX: str = "!"
ALL_PREFIXES: Tuple[str, ...] = SCOPED_PREFIXES + (GLOBAL_PREFIX,)
PREFIX_LABELS = {
    "!sc": "Scribe",
    "!rem": "Reminder",
    "!wc": "Welcome Crew",
    "!mm": "Matchmaker",
}


def get_prefix(_bot: Any, _message: Any) -> Sequence[str]:
    """Return the runtime prefix list for discord.py."""
    return ALL_PREFIXES


def is_scoped_prefix(prefix: str) -> bool:
    """Return True if the prefix is one of the scoped CoreOps prefixes."""
    return prefix.lower() in {p.lower() for p in SCOPED_PREFIXES}
