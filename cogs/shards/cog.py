from __future__ import annotations
import asyncio
from typing import Dict, Tuple, Optional, List
from datetime import datetime, timezone
import time
import logging
import discord
from discord.ext import commands

from .constants import ShardType, Rarity, DISPLAY_ORDER
from . import sheets_adapter as SA
from .views import SetCountsModal, AddPullsStart, AddPullsCount, AddPullsRarities
from .renderer import build_summary_embed
import io
from .ocr import extract_counts_from_image_bytes, ocr_runtime_info, ocr_smoke_test

log = logging.getLogger("c1c-claims")

UTC = timezone.utc

def _has_any_role(member: discord.Member, role_ids: List[int]) -> bool:
    rids = {r.id for r in member.roles}
    return any(r in rids for r in role_ids)

class ShardsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfg, self.clans = SA.load_config()  # wire to Sheets
        self._live_views: Dict[int, discord.ui.View] = {}  # keep views referenced until timeout
        
        # Log OCR stack once for visibility
        try:
            info = ocr_runtime_info()
            if info:
                log.info("[ocr] tesseract=%s | pytesseract=%s | pillow=%s",
                         info.get("tesseract_version"), info.get("pytesseract_version"), info.get("pillow_version"))
            else:
                log.warning("[ocr] runtime info unavailable (pytesseract/Pillow not importable)")
        except Exception:
            log.exception("[ocr] failed to query OCR runtime info")


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
    
    # --- OCR helper (reads the attachment and returns {ShardType:int}) ---
    async def _ocr_prefill_from_attachment(self, att: discord.Attachment) -> Dict[ShardType, int]:
        data = await att.read()
        return extract_counts_from_image_bytes(data) or {}
    
    # --- Background: prime OCR cache so button clicks are instant ---
    async def _cache_ocr_for_message(self, msg_id: int, att: discord.Attachment) -> None:
        try:
            data = await att.read()
            pre = await asyncio.to_thread(extract_counts_from_image_bytes, data)  # CPU/subprocess off-thread
            if pre:
                self._ocr_cache[msg_id] = pre
        except Exception:
            # ignore OCR failures; modal will just open blank
            pass

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
        
        # Build the images list for OCR
        images = [a for a in message.attachments if (a.content_type or "").startswith("image/")]
        
        async def _submit_counts(modal_inter: discord.Interaction, counts: Dict[ShardType, int]):
            if not any(counts.values()):
                await modal_inter.response.send_message("No numbers provided.", ephemeral=True)
                return
            clan_tag = self._clan_tag_for_thread(message.channel.id) or ""
            SA.append_snapshot(message.author.id, message.author.display_name, clan_tag, counts, "manual", message.jump_url)
            await self._refresh_summary_for_clan(clan_tag)
            await modal_inter.response.send_message("Counts saved. Summary updated.", ephemeral=True)
        
        async def _open_modal(inter: discord.Interaction):
            if inter.user.id != message.author.id and not _has_any_role(inter.user, self.cfg.roles_staff_override):
                await inter.response.send_message("Only the image author or staff can review this.", ephemeral=True)
                return
            clan_tag = self._clan_tag_for_thread(message.channel.id) or ""

            # use whatever OCR finished; if not ready, modal still opens instantly
            prefill = dict(self._ocr_cache.get(message.id, {}) or {})

            def _fetch_last_snapshot() -> Optional[Dict[ShardType, int]]:
                snap = SA.get_last_inventory(message.author.id, clan_tag if clan_tag else None)
                if not snap and clan_tag:
                    snap = SA.get_last_inventory(message.author.id)
                return snap

            fallback_counts: Optional[Dict[ShardType, int]] = None
            if not prefill or not any(prefill.values()):
                fallback_counts = _fetch_last_snapshot()

            if fallback_counts:
                if not prefill:
                    prefill = dict(fallback_counts)
                else:
                    for st, val in fallback_counts.items():
                        if prefill.get(st, 0) <= 0 and val:
                            prefill[st] = val

            if prefill:
                prefill = {st: prefill.get(st, 0) for st in ShardType}

            modal = SetCountsModal(prefill=prefill or None)
            await inter.response.send_modal(modal)
            # wait for the user to submit the modal, then parse and save
            timed_out = await modal.wait()
            if timed_out:
                return
            counts = modal.parse_counts()
            if not any(counts.values()):
                await inter.followup.send("No numbers provided.", ephemeral=True)
                return

            SA.append_snapshot(message.author.id, message.author.display_name, clan_tag, counts, "manual", message.jump_url)
            await self._refresh_summary_for_clan(clan_tag)
            await inter.followup.send("Counts saved. Summary updated.", ephemeral=True)

        btn.callback = _open_modal
        view.add_item(btn)
        msg = await message.channel.send("Spotted a shard screen. Want me to read it?", view=view)
        self._live_views[msg.id] = view
        
        # prime OCR in the background (don’t block the button interaction)
        asyncio.create_task(self._cache_ocr_for_message(message.id, images[0]))  # ← ADDED
        
        # tidy up refs after timeout
        async def _drop():
            try:
                await asyncio.sleep((view.timeout or 120) + 5)
            except Exception:
                pass
            self._live_views.pop(msg.id, None)
            self._ocr_cache.pop(message.id, None)  # ← ADDED
        
        asyncio.create_task(_drop())

    # ---------- OCR DIAGNOSTICS ----------
    @commands.command(name="ocr")
    async def ocr_cmd(self, ctx: commands.Context, sub: Optional[str] = None):
        """
        Staff diagnostics:
          • !ocr info      → show OCR versions
          • !ocr selftest  → run '12345' smoke test
        """
        # optional: restrict to staff
        if not _has_any_role(ctx.author, getattr(self.cfg, "roles_staff_override", [])):
            return await ctx.reply("Staff only.", mention_author=False)

        s = (sub or "").strip().lower()
        if s in ("info", "ver", "version"):
            info = ocr_runtime_info()
            if not info:
                return await ctx.reply("OCR runtime info unavailable (pytesseract/Pillow not importable).", mention_author=False)
            return await ctx.reply(
                f"Tesseract: **{info.get('tesseract_version','?')}** | "
                f"pytesseract: **{info.get('pytesseract_version','?')}** | "
                f"Pillow: **{info.get('pillow_version','?')}**",
                mention_author=False
            )

        if s in ("selftest", "test"):
            t0 = time.perf_counter()
            ok, text = ocr_smoke_test()
            ms = int((time.perf_counter() - t0) * 1000)
            status = "PASS ✅" if ok else "FAIL ❌"
            return await ctx.reply(
                f"OCR self-test: **{status}** in **{ms} ms**. Read: `{text or '∅'}` (expected `12345`).",
                mention_author=False
            )

        await ctx.reply("Usage: `!ocr info` or `!ocr selftest`.", mention_author=False)

    # ---------- COMMANDS ----------
    @commands.command(name="shards")
    async def shards_cmd(self, ctx: commands.Context, sub: Optional[str] = None, *, tail: Optional[str] = None):
:
        if not isinstance(ctx.channel, discord.Thread) or not self._is_shard_thread(ctx.channel):
            await ctx.reply("This command only works in your clan’s shard thread.")
            return

        sub = (sub or "").lower()
        if sub in {"", "help"}:
            await self._cmd_shards_help(ctx); return
        if sub == "set":
            await self._cmd_shards_set(ctx, tail); return
        await ctx.reply("Unknown subcommand. Try `!shards help`.")

    async def _cmd_shards_help(self, ctx: commands.Context):
        text = (
            "**Shard & Mercy — Quick Guide**\n"
            "Post a shard screenshot or type `!shards set` to enter counts for {EMJ_MYS} {EMJ_ANC} {EMJ_VOID} {EMJ_PRI} {EMJ_SAC}.\n"
            "During pull sessions use `!mercy addpulls` → pick shard → number of pulls.\n"
            "If you hit **Epic/Legendary/Mythical**, I’ll ask **how many pulls were left after the last one**.\n"
            "**Guaranteed**/**Extra Legendary** don’t reset mercy—tick the flag.\n"
            "Staff can manage others with `for:@user`. Pinned message shows everyone (10 per page)."
        )
        await ctx.reply(text)

    async def _cmd_shards_set(self, ctx: commands.Context, tail: Optional[str]):
        # staff override parsing (for:@user) — simple/forgiving
        target: discord.Member = ctx.author
        if tail and "for:" in tail:
            if not _has_any_role(ctx.author, self.cfg.roles_staff_override):
                await ctx.reply("You need a staff role to manage data for others."); return
            if ctx.message.mentions:
                target = ctx.message.mentions[0]

        view = discord.ui.View(timeout=60)
        btn = discord.ui.Button(label="Open Set Shard Counts", style=discord.ButtonStyle.primary)

        async def _open(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                await inter.response.send_message("This button is not for you.", ephemeral=True); return
        
            modal = SetCountsModal(prefill=None)  # no on_submit_cb
            await inter.response.send_modal(modal)
        
            timed_out = await modal.wait()
            if timed_out:
                return
            counts = modal.parse_counts()
            if not any(counts.values()):
                await inter.followup.send("No numbers provided.", ephemeral=True); return
        
            clan_tag = self._clan_tag_for_thread(ctx.channel.id) or (self._clan_for_member(target) or "")
            SA.append_snapshot(target.id, target.display_name, clan_tag, counts, "manual", ctx.message.jump_url)
            await self._refresh_summary_for_clan(clan_tag)
            await inter.followup.send("Counts saved. Summary updated.", ephemeral=True)

        btn.callback = _open
        view.add_item(btn)
        await ctx.reply("Click to open the form:", view=view)

    @commands.command(name="mercy")
    async def mercy_cmd(self, ctx: commands.Context, sub: Optional[str] = None, *, tail: Optional[str] = None):
        if not isinstance(ctx.channel, discord.Thread) or not self._is_shard_thread(ctx.channel):
            await ctx.reply("This command only works in your clan’s shard thread.")
            return
        sub = (sub or "").lower()
        if sub == "addpulls":
            await self._cmd_addpulls(ctx, tail); return
        await ctx.reply("Subcommands: `addpulls` (now). `reset`, `set`, `show` (Phase 2).")

    async def _cmd_addpulls(self, ctx: commands.Context, tail: Optional[str]):
        # Step 1: pick shard via buttons
        start = AddPullsStart(author_id=ctx.author.id)
        msg = await ctx.reply("Pick a shard:", view=start)

        def _check_shard(i: discord.Interaction):
            cid = (i.data or {}).get("custom_id", "")
            return i.message.id == msg.id and i.user.id == ctx.author.id and str(cid).startswith("addpulls:shard:")

        try:
            inter: discord.Interaction = await self.bot.wait_for("interaction", timeout=120, check=_check_shard)
        except asyncio.TimeoutError:
            return

        shard_val = inter.data["custom_id"].split(":")[-1]
        shard = ShardType(shard_val)

        # Step 2: how many pulls
        count_modal = AddPullsCount(shard)
        await inter.response.send_modal(count_modal)
        await count_modal.wait()
        N = count_modal.count()

        # Mystery: inventory-only event
        if shard == ShardType.MYSTERY:
            SA.append_events([{
                "ts_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "actor_discord_id": str(ctx.author.id),
                "target_discord_id": str(ctx.author.id),
                "clan_tag": self._clan_tag_for_thread(ctx.channel.id) or "",
                "type": "pull",
                "shard_type": shard.value,
                "rarity": "",
                "qty": N,
                "note": "batch",
                "origin": "command",
                "message_link": ctx.message.jump_url,
                "guaranteed_flag": False,
                "extra_legendary_flag": False,
                "batch_id": f"b{ctx.message.id}",
                "batch_size": N,
                "index_in_batch": "",
                "resets_pity": False,
            }])
            await self._refresh_summary_for_clan(self._clan_tag_for_thread(ctx.channel.id))
            await ctx.reply("Pulls recorded. Summary updated.")
            return

        # Step 3: rarities (batch-aware)
        rar_modal = AddPullsRarities(shard, N)

        # open a small button to trigger modal from a prefix command
        v = discord.ui.View(timeout=60)
        open_btn = discord.ui.Button(label="Open rarity form", style=discord.ButtonStyle.primary)

        async def _open2(i: discord.Interaction):
            if i.user.id != ctx.author.id:
                await i.response.send_message("Not for you.", ephemeral=True); return
            await i.response.send_modal(rar_modal)

        open_btn.callback = _open2
        v.add_item(open_btn)
        await ctx.reply("Click to specify rarities:", view=v)
        await rar_modal.wait()
        data = rar_modal.parse()

        # Build ledger rows (batch-aware)
        batch_id = f"b{ctx.message.id}"
        rows: List[Dict] = []
        base = {
            "ts_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actor_discord_id": str(ctx.author.id),
            "target_discord_id": str(ctx.author.id),
            "clan_tag": self._clan_tag_for_thread(ctx.channel.id) or "",
            "shard_type": shard.value,
            "origin": "command",
            "message_link": ctx.message.jump_url,
            "batch_id": batch_id,
            "batch_size": N,
        }
        # aggregate pull row
        rows.append({**base, "type": "pull", "rarity": "", "qty": N,
                     "note": "batch", "guaranteed_flag": False, "extra_legendary_flag": False,
                     "index_in_batch": "", "resets_pity": False})

        guar = bool(data.get("guaranteed", False))
        extra = bool(data.get("extra", False))

        if shard in (ShardType.ANCIENT, ShardType.VOID):
            if data.get("epic", False):
                rows.append({**base, "type": "epic", "rarity": "epic", "qty": 1, "note": "",
                             "guaranteed_flag": False, "extra_legendary_flag": False,
                             "index_in_batch": N - int(data.get("epic_left", 0)), "resets_pity": True})
            if data.get("legendary", False):
                rows.append({**base, "type": "legendary", "rarity": "legendary", "qty": 1,
                             "note": "guaranteed" if guar else ("extra" if extra else ""),
                             "guaranteed_flag": guar, "extra_legendary_flag": extra,
                             "index_in_batch": N - int(data.get("legendary_left", 0)),
                             "resets_pity": not (guar or extra)})
        elif shard == ShardType.SACRED:
            if data.get("legendary", False):
                rows.append({**base, "type": "legendary", "rarity": "legendary", "qty": 1,
                             "note": "guaranteed" if guar else ("extra" if extra else ""),
                             "guaranteed_flag": guar, "extra_legendary_flag": extra,
                             "index_in_batch": N - int(data.get("legendary_left", 0)),
                             "resets_pity": not (guar or extra)})
        elif shard == ShardType.PRIMAL:
            if data.get("legendary", False):
                rows.append({**base, "type": "legendary", "rarity": "legendary", "qty": 1,
                             "note": "guaranteed" if guar else ("extra" if extra else ""),
                             "guaranteed_flag": guar, "extra_legendary_flag": extra,
                             "index_in_batch": N - int(data.get("legendary_left", 0)),
                             "resets_pity": not (guar or extra)})
            if data.get("mythical", False):
                rows.append({**base, "type": "mythical", "rarity": "mythical", "qty": 1,
                             "note": "guaranteed" if guar else ("extra" if extra else ""),
                             "guaranteed_flag": guar, "extra_legendary_flag": extra,
                             "index_in_batch": N - int(data.get("mythical_left", 0)),
                             "resets_pity": not (guar or extra)})

        SA.append_events(rows)
        await self._refresh_summary_for_clan(self._clan_tag_for_thread(ctx.channel.id))
        await ctx.reply("Pulls recorded. Summary updated.")

    # ---------- SUMMARY ----------
    async def _refresh_summary_for_clan(self, clan_tag: Optional[str]):
        if not clan_tag:
            return
        cc = self.clans.get(clan_tag)
        if not cc:
            return

        # TODO: fetch real state from Sheets; placeholders keep the scaffold running
        participants = 0
        totals = {st: 0 for st in DISPLAY_ORDER}
        page_index = 0
        members_page: List[tuple[str, dict, dict]] = []
        top_risers: List[str] = []

        embed = build_summary_embed(
            clan_name=cc.clan_name,
            emoji_map=self.cfg.emoji,
            participants=participants,
            totals=totals,
            page_index=page_index,
            page_size=self.cfg.page_size,
            members_page=members_page,
            top_risers=top_risers,
            updated_dt=datetime.now(UTC),
        )

        thread_id, pinned_id = SA.get_summary_msg(clan_tag)
        thread = self.bot.get_channel(thread_id) if thread_id else None
        if not thread:
            thread = self.bot.get_channel(cc.thread_id) or await self.bot.fetch_channel(cc.thread_id)

        if pinned_id:
            try:
                msg = await thread.fetch_message(pinned_id)
                await msg.edit(embed=embed)
                return
            except Exception:
                pass

        msg = await thread.send(embed=embed)
        try:
            await msg.pin(reason="Shard & Mercy summary")
        except Exception:
            pass
        SA.set_summary_msg(clan_tag, thread.id, msg.id, self.cfg.page_size, 1)
