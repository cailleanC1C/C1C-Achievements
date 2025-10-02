from __future__ import annotations
import asyncio
from typing import Dict, Tuple, Optional, List
from datetime import datetime, timezone
import discord
from discord.ext import commands

from .constants import ShardType, Rarity, DISPLAY_ORDER
from . import sheets_adapter as SA
from .views import SetCountsModal, AddPullsStart, AddPullsCount, AddPullsRarities
from .renderer import build_summary_embed

UTC = timezone.utc

def _has_any_role(member: discord.Member, role_ids: List[int]) -> bool:
    rids = {r.id for r in member.roles}
    return any(r in rids for r in role_ids)

class ShardsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfg, self.clans = SA.load_config()  # wire to Sheets

    # ---------- GUARDS ----------
    def _clan_for_member(self, member: discord.Member) -> Optional[str]:
        for ct, cc in self.clans.items():
            if cc.is_enabled and cc.role_id in [r.id for r in member.roles]:
                return ct
        return None

    def _is_shard_thread(self, channel: discord.abc.GuildChannel) -> bool:
        if isinstance(channel, discord.Thread):
            return any(channel.id == cc.thread_id for cc in self.clans.values() if cc.is_enabled)
        return False

    def _clan_tag_for_thread(self, thread_id: int) -> Optional[str]:
        for ct, cc in self.clans.items():
            if cc.thread_id == thread_id and cc.is_enabled:
                return ct
        return None

    # ---------- WATCHER: images in shard threads ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.Thread):
            return
        if not self._is_shard_thread(message.channel):
            return
        if not (message.attachments and any(a.content_type and a.content_type.startswith("image/") for a in message.attachments)):
            return

        view = discord.ui.View(timeout=120)
        btn = discord.ui.Button(label="Review Shards", style=discord.ButtonStyle.primary)

        async def _open_modal(inter: discord.Interaction):
            if inter.user.id != message.author.id and not _has_any_role(inter.user, self.cfg.roles_staff_override):
                await inter.response.send_message("Only the image author or staff can review this.", ephemeral=True)
                return
            modal = SetCountsModal(prefill=None)  # TODO: OCR prefill
            await inter.response.send_modal(modal)
            timed_out = await modal.wait()
            if timed_out:
                return
            counts = modal.parse_counts()
            if not any(counts.values()):
                await inter.followup.send("No numbers provided.", ephemeral=True)
                return
            target = message.author
            SA.append_snapshot(target.id, target.display_name, self._clan_tag_for_thread(message.channel.id) or "", counts, "manual", message.jump_url)
            await self._refresh_summary_for_clan(self._clan_tag_for_thread(message.channel.id))
            await inter.followup.send("Counts saved. Summary updated.", ephemeral=True)

        btn.callback = _open_modal
        view.add_item(btn)
        await message.channel.send("Spotted a shard screen. Want me to read it?", view=view)

    # ---------- COMMANDS ----------
    @commands.command(name="shards")
    async def shards_cmd(self, ctx: commands.Context, sub: Optional[str] = None_
