import discord

import c1c_claims_appreciation as app


class FakeAsset:
    def __init__(self, url):
        self.url = url

    def with_size(self, size):
        return FakeAsset(f"{self.url}?size={size}")


class FakeEmoji:
    def __init__(self, emoji_id, name="sparkle", url="https://cdn.example/emoji.png", animated=False):
        self.id = emoji_id
        self.name = name
        self.url = url
        self.animated = animated


class FakeRole:
    def __init__(self, *, icon_url=None, color=None, name="Achievement Role"):
        self.name = name
        self.display_icon = FakeAsset(icon_url) if icon_url else None
        self.icon = None
        self.color = color or discord.Color.default()


class FakeGuild:
    def __init__(self, emojis=()):
        self.emojis = list(emojis)


class FakeUser:
    display_name = "Tester"
    mention = "<@123>"


def _row(emoji_value, **overrides):
    row = {
        "EmojiNameOrId": emoji_value,
        "Title": "Great job, {user}!",
        "Body": "Unlocked {role} {emoji}",
        "Footer": "Footer {role}",
        "ColorHex": "#123456",
    }
    row.update(overrides)
    return row


def _embed_dict(embed):
    return embed.to_dict()


def test_role_icon_wins_over_emoji_fallback():
    emoji = FakeEmoji(152503451646828746, url="https://cdn.example/emoji.png")
    guild = FakeGuild([emoji])
    role = FakeRole(icon_url="https://cdn.example/role.png")

    assert app.resolve_praise_thumbnail_url(role, str(emoji.id), guild=guild) == "https://cdn.example/role.png?size=512"

    embed = app.build_achievement_embed(guild, FakeUser(), role, _row(str(emoji.id)))
    assert _embed_dict(embed)["thumbnail"]["url"] == "https://cdn.example/role.png?size=512"


def test_existing_hero_thumbnail_wins_over_emoji_fallback():
    emoji = FakeEmoji(152503451646828746, url="https://cdn.example/emoji.png")
    guild = FakeGuild([emoji])
    role = FakeRole()

    embed = app.build_achievement_embed(
        guild,
        FakeUser(),
        role,
        _row(str(emoji.id), HeroImageURL="https://cdn.example/hero.png"),
    )

    assert _embed_dict(embed)["thumbnail"]["url"] == "https://cdn.example/hero.png"


def test_numeric_emoji_id_resolves_to_thumbnail_when_role_has_no_icon():
    emoji = FakeEmoji(152503451646828746, url="https://cdn.example/numeric.png")
    guild = FakeGuild([emoji])
    role = FakeRole()

    embed = app.build_achievement_embed(guild, FakeUser(), role, _row("152503451646828746"))

    assert _embed_dict(embed)["thumbnail"]["url"] == "https://cdn.example/numeric.png"


def test_custom_emoji_mention_resolves_to_thumbnail_when_role_has_no_icon():
    emoji = FakeEmoji(152503451646828746, url="https://cdn.example/mention.png")
    guild = FakeGuild([emoji])
    role = FakeRole()

    embed = app.build_achievement_embed(guild, FakeUser(), role, _row("<:sparkle:152503451646828746>"))

    assert _embed_dict(embed)["thumbnail"]["url"] == "https://cdn.example/mention.png"


def test_group_embed_uses_guild_only_emoji_fallback_without_global_bot(monkeypatch):
    emoji = FakeEmoji(152503451646828746, url="https://cdn.example/group.png")
    guild = FakeGuild([emoji])
    role = FakeRole()
    monkeypatch.delattr(app, "bot", raising=False)

    embed = app.build_group_embed(guild, FakeUser(), [(role, _row(str(emoji.id)))])

    assert _embed_dict(embed)["thumbnail"]["url"] == "https://cdn.example/group.png"


def test_invalid_or_unresolved_emoji_does_not_set_thumbnail_or_block_embed():
    guild = FakeGuild([])
    role = FakeRole()

    for value in ("", "not-a-real-emoji", "😀", "999999999"):
        embed = app.build_achievement_embed(guild, FakeUser(), role, _row(value))
        data = _embed_dict(embed)
        assert "thumbnail" not in data
        assert data["title"] == "Great job, <@123>!"


def test_existing_title_body_footer_and_color_behavior_remains_unchanged():
    emoji = FakeEmoji(152503451646828746, name="sparkle", url="https://cdn.example/emoji.png")
    guild = FakeGuild([emoji])
    role = FakeRole(name="Helper")

    embed = app.build_achievement_embed(guild, FakeUser(), role, _row(str(emoji.id)))
    data = _embed_dict(embed)

    assert data["title"] == "Great job, <@123>!"
    assert data["description"] == "Unlocked Helper <:sparkle:152503451646828746>"
    assert data["footer"]["text"] == "Footer Helper"
    assert data["color"] == int("123456", 16)
