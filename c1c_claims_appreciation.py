EMOJI_TAG_RE = re.compile(r"^<a?:\w+:\d+>$")

def _to_str(x) -> str:
    """Coerce any cell value to a clean string (handles ints/floats from Excel/Sheets)."""
    if x is None:
        return ""
    if isinstance(x, float):
        # if it's a whole number like 12345.0, show 12345
        return str(int(x)) if x.is_integer() else str(x)
    if isinstance(x, int):
        return str(x)
    return str(x)

def resolve_emoji_text(guild: discord.Guild, value: Optional[str], fallback: Optional[str]=None) -> str:
    """
    Accepts unicode emoji, <:name:id>, numeric id, or a name.
    Works even if the sheet gives us numbers (int/float).
    """
    v = _to_str(value).strip()
    if not v:
        v = _to_str(fallback).strip()
    if not v:
        return ""

    # Already a proper <...:id> tag
    if EMOJI_TAG_RE.match(v):
        return v

    # Pure numeric: treat as a custom emoji ID
    if v.isdigit():
        e = discord.utils.get(guild.emojis, id=int(v))
        return f"<{'a' if e.animated else ''}:{e.name}:{e.id}>" if e else ""

    # Otherwise, try by name; if not found, assume it's unicode and return as-is
    e = discord.utils.get(guild.emojis, name=v)
    return f"<{'a' if e.animated else ''}:{e.name}:{e.id}>" if e else v

def _color_from_hex(hex_str: Optional[str]) -> Optional[discord.Color]:
    """Be tolerant: accept '#14532D', '14532D', or even numeric cells."""
    if hex_str in (None, ""):
        return None
    try:
        s = _to_str(hex_str).strip().lstrip("#")
        return discord.Color(int(s, 16))
    except Exception:
        return None
