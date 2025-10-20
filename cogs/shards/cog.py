from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from typing import Dict, Optional, List
from datetime import datetime, timezone

import discord
from discord.ext import commands

from .constants import ShardType, Rarity, DISPLAY_ORDER
from . import sheets_adapter as SA
from .views import SetCountsModal, AddPullsStart, AddPullsCount, AddPullsRarities
from .renderer import build_summary_embed
from .ocr import (
    collect_debug_bundle,
    extract_counts_from_image_bytes,
    extract_counts_with_debug,
    ocr_runtime_info,
    ocr_smoke_test,
)

UTC = timezone.utc
log = logging.getLogger("c1c-claims")


def _has_any_role(member: discord.Member, role_ids: List[int]) -> bool:
    rids = {r.id for r in member.roles}
    return any(r in rids for r in role_ids)


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _is_image_attachment(att: discord.Attachment) -> bool:
    """Lenient check for images (content-type or filename)."""
    ct = (att.content_type or "").lower().split(";")[0].strip()
    if ct.startswith("image/"):
        return True
    fn = (att.filename or "").lower()
    return fn.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))


class ShardsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfg, self.clans = SA.load_config()  # wire to Sheets
        self._live_views: Dict[int, discord.ui.View] = {}  # keep views referenced until timeout
        self._ocr_cache: Dict[tuple[int, int, int], Dict[ShardType, int]] = {}  # (guild_id, channel_id, msg_id) -> counts
        self._ocr_debug_enabled = _env_truthy("ENABLE_OCR_DEBUG", False)
        self._last_debug_image: Optional[bytes] = None

        # Log OCR stack once for visibility
        try:
            info = ocr_runtime_info()
            if info:
                log.info(
                    "[ocr] tesseract=%s (cli=%s) | pytesseract=%s | pillow=%s",
                    info.get("tesseract_version"),
                    info.get("tesseract_cli_version"),
                    info.get("pytesseract_version"),
                    info.get("pillow_version"),
                )
                langs = info.get("tesseract_languages")
                if langs:
                    log.info("[ocr] tesseract languages: %s", langs)
            else:
                log.warning("[ocr] runtime info unavailable (pytesseract/Pillow not importable)")
        except Exception:
            log.exception("[ocr] failed to query OCR runtime info")

        log.info(
            "[ocr] debug command enabled=%s (guild allow-list disabled for Achievements bot)",
            self._ocr_debug_enabled,
        )

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
        try:
            data = await self._read_attachment_bytes(att)
            if not data:
                raise RuntimeError("attachment read returned no data")
            self._last_debug_image = data
            counts = await asyncio.to_thread(extract_counts_from_image_bytes, data) or {}
            # normalize missing keys so the preview always has all five
            for st in ShardType:
                counts.setdefault(st, 0)
            return counts
        except Exception:
            return {st: 0 for st in ShardType}

    async def _read_attachment_bytes(self, att: discord.Attachment, timeout: float = 10.0) -> Optional[bytes]:
        try:
            return await asyncio.wait_for(att.read(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("[ocrdebug] timed out reading attachment %s", getattr(att, "id", "?"))
            return None
        except Exception:
            log.warning("[ocrdebug] failed to read attachment %s", getattr(att, "id", "?"), exc_info=True)
            return None

    async def _resolve_debug_image_bytes(self, ctx: commands.Context) -> Optional[bytes]:
        """Resolve an image for OCR debug following attachment/reply/history priority."""
        # 1) attachment on the command message
        for att in getattr(ctx.message, "attachments", []):
            if _is_image_attachment(att):
                data = await self._read_attachment_bytes(att)
                if data:
                    self._last_debug_image = data
                    return data

        # 2) attachment on the replied-to message
        reference = getattr(ctx.message, "reference", None)
        resolved_msg: Optional[discord.Message] = None
        if reference:
            resolved = getattr(reference, "resolved", None)
            if isinstance(resolved, discord.Message):
                resolved_msg = resolved
            elif reference.message_id and getattr(ctx, "channel", None):
                try:
                    resolved_msg = await ctx.channel.fetch_message(reference.message_id)
                except Exception:
                    resolved_msg = None
        if resolved_msg:
            for att in getattr(resolved_msg, "attachments", []):
                if _is_image_attachment(att):
                    data = await self._read_attachment_bytes(att)
                    if data:
                        self._last_debug_image = data
                        return data

        # 3) scan recent history (bounded)
        channel = getattr(ctx, "channel", None)
        if channel is not None:
            try:
                async for msg in channel.history(limit=30):
                    if msg.id == ctx.message.id:
                        continue
                    for att in getattr(msg, "attachments", []):
                        if _is_image_attachment(att):
                            data = await self._read_attachment_bytes(att)
                            if data:
                                self._last_debug_image = data
                                return data
            except Exception:
                log.warning("[ocrdebug] failed to inspect recent channel history", exc_info=True)

        # 4) fallback to the last cached debug image if any
        if self._last_debug_image:
            log.info("[ocrdebug] using cached image from last run")
            return self._last_debug_image
        return None

    # ---------- UTIL: formatting ----------
    def _emoji_or_abbr(self, st: ShardType) -> str:
        """Try custom emoji from config; else fallback to colored label."""
        emap = getattr(self.cfg, "emoji", None) or {}
        fallback = {
            ShardType.MYSTERY: "🟩Myst",
            ShardType.ANCIENT: "🟦Anc",
            ShardType.VOID:    "🟪Void",
            ShardType.PRIMAL:  "🟥Pri",
            ShardType.SACRED:  "🟨Sac",
        }
        key_map = {
            ShardType.MYSTERY: ("Myst", "Mystery"),
            ShardType.ANCIENT: ("Anc", "Ancient"),
            ShardType.VOID:    ("Void",),
            ShardType.PRIMAL:  ("Pri", "Primal"),
            ShardType.SACRED:  ("Sac", "Sacred"),
        }
        for k in key_map.get(st, ()):
            val = emap.get(k)
            if val:
                return f"{val} {k}"
        return fallback.get(st, st.value)

    def _fmt_counts_line(self, counts: Dict[ShardType, int]) -> str:
        order = [ShardType.MYSTERY, ShardType.ANCIENT, ShardType.VOID, ShardType.PRIMAL, ShardType.SACRED]
        parts = []
        for st in order:
            label = self._emoji_or_abbr(st)
            num = counts.get(st, 0)
            parts.append(f"{label} {num}")
        return " · ".join(parts)

    # ---------- WATCHER: images in shard threads ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.Thread):
            return
        if not self._is_shard_thread(message.channel):
            return
        if not (message.attachments and any(_is_image_attachment(a) for a in message.attachments)):
            return

        images = [a for a in message.attachments if _is_image_attachment(a)]
        if not images:
            return

        # Post ROI debug images (only when OCR returns all zeros) to help tuning
        async def _ocr_debug_background():
            try:
                data = await images[0].read()
                self._last_debug_image = data
                counts, dbg_imgs = await asyncio.to_thread(extract_counts_with_debug, data, 8)
                if sum(counts.values()) == 0 and dbg_imgs:
                    import io as _io
                    files = [discord.File(_io.BytesIO(b), filename=name) for name, b in dbg_imgs]
                    await message.channel.send(
                        content="(OCR debug) Left-rail ROI I’m reading (grayscale + binarized).",
                        files=files,
                    )
            except Exception:
                pass

        asyncio.create_task(_ocr_debug_background())

        # Public prompt with buttons
        view = discord.ui.View(timeout=300)
        scan_btn = discord.ui.Button(
            label="Scan Image", style=discord.ButtonStyle.primary, custom_id=f"shards:scan:{message.id}"
        )
        dismiss_btn = discord.ui.Button(
            label="Dismiss", style=discord.ButtonStyle.secondary, custom_id=f"shards:dismiss:{message.id}"
        )

        async def _scan_callback(inter: discord.Interaction):
            # Only the image author or staff
            if inter.user.id != message.author.id and not _has_any_role(
                inter.user, getattr(self.cfg, "roles_staff_override", [])
            ):
                try:
                    await inter.response.send_message("Only the image author or staff can scan this.", ephemeral=True)
                except Exception:
                    pass
                return

            # Defer quickly to avoid Unknown interaction
            try:
                await inter.response.defer(ephemeral=True, thinking=True)
            except Exception:
                pass

            cache_key = (message.guild.id if message.guild else 0, message.channel.id, message.id)
            counts = self._ocr_cache.get(cache_key)
            if not counts:
                counts = await self._ocr_prefill_from_attachment(images[0])
                self._ocr_cache[cache_key] = counts

            preview = self._fmt_counts_line(counts)

            # Ephemeral control panel
            eview = discord.ui.View(timeout=180)

            use_btn = discord.ui.Button(
                label="Use these counts", style=discord.ButtonStyle.success, custom_id=f"shards:use:{message.id}"
            )
            manual_btn = discord.ui.Button(
                label="Manual entry", style=discord.ButtonStyle.primary, custom_id=f"shards:manual:{message.id}"
            )
            retry_btn = discord.ui.Button(
                label="Retry OCR", style=discord.ButtonStyle.secondary, custom_id=f"shards:retry:{message.id}"
            )
            close_btn = discord.ui.Button(
                label="Close", style=discord.ButtonStyle.danger, custom_id=f"shards:close:{message.id}"
            )

            async def _use_counts(i2: discord.Interaction):
                if i2.user.id != inter.user.id:
                    await i2.response.send_message("Not your panel.", ephemeral=True)
                    return
                modal = SetCountsModal(prefill=counts)
                await i2.response.send_modal(modal)
                try:
                    await modal.wait()
                except Exception:
                    pass
                try:
                    parsed = modal.parse_counts()
                except Exception:
                    parsed = counts or {}

                if not any(parsed.values()):
                    await i2.followup.send("No numbers provided.", ephemeral=True)
                    return

                clan_tag = self._clan_tag_for_thread(message.channel.id) or ""
                SA.append_snapshot(
                    message.author.id, message.author.display_name, clan_tag, parsed, "manual", message.jump_url
                )
                await self._refresh_summary_for_clan(clan_tag)
                await i2.followup.send("Counts saved. Summary updated.", ephemeral=True)

            async def _manual(i2: discord.Interaction):
                if i2.user.id != inter.user.id:
                    await i2.response.send_message("Not your panel.", ephemeral=True)
                    return
                modal = SetCountsModal(prefill=None)
                await i2.response.send_modal(modal)
                try:
                    await modal.wait()
                except Exception:
                    pass
                try:
                    parsed = modal.parse_counts()
                except Exception:
                    parsed = {}

                if not any(parsed.values()):
                    await i2.followup.send("No numbers provided.", ephemeral=True)
                    return

                clan_tag = self._clan_tag_for_thread(message.channel.id) or ""
                SA.append_snapshot(
                    message.author.id, message.author.display_name, clan_tag, parsed, "manual", message.jump_url
                )
                await self._refresh_summary_for_clan(clan_tag)
                await i2.followup.send("Counts saved. Summary updated.", ephemeral=True)

            async def _retry(i2: discord.Interaction):
                if i2.user.id != inter.user.id:
                    await i2.response.send_message("Not your panel.", ephemeral=True)
                    return
                # Defer first, then heavy work off-thread, then edit original ephemeral message
                try:
                    await i2.response.defer(ephemeral=True, thinking=True)
                except Exception:
                    pass
                self._ocr_cache.pop(cache_key, None)
                new_counts = await self._ocr_prefill_from_attachment(images[0])
                self._ocr_cache[cache_key] = new_counts
                new_preview = self._fmt_counts_line(new_counts)
                try:
                    await i2.edit_original_response(content=f"**OCR Preview**\n{new_preview}", view=eview)
                except Exception:
                    # Fallback: send a fresh ephemeral message
                    await i2.followup.send(f"**OCR Preview**\n{new_preview}", ephemeral=True)

            async def _close(i2: discord.Interaction):
                if i2.user.id != inter.user.id:
                    await i2.response.send_message("Not your panel.", ephemeral=True)
                    return
                try:
                    await i2.response.defer(ephemeral=True)
                except Exception:
                    pass
                try:
                    await i2.edit_original_response(content="Closed.", view=None)
                except Exception:
                    pass

            use_btn.callback = _use_counts
            manual_btn.callback = _manual
            retry_btn.callback = _retry
            close_btn.callback = _close

            eview.add_item(use_btn)
            eview.add_item(manual_btn)
            eview.add_item(retry_btn)
            eview.add_item(close_btn)

            try:
                ep_msg = await inter.followup.send(f"**OCR Preview**\n{preview}", view=eview, ephemeral=True)
                # Keep a reference so callbacks remain alive
                self._live_views[getattr(ep_msg, "id", 0) or 0] = eview
            except Exception:
                pass

        async def _dismiss_callback(inter: discord.Interaction):
            if inter.user.id != message.author.id and not _has_any_role(
                inter.user, getattr(self.cfg, "roles_staff_override", [])
            ):
                try:
                    await inter.response.send_message("Only the image author or staff can dismiss this.", ephemeral=True)
                except Exception:
                    pass
                return
            try:
                await inter.response.defer()
            except Exception:
                pass
            try:
                await prompt.delete()
            except Exception:
                pass

        scan_btn.callback = _scan_callback
        dismiss_btn.callback = _dismiss_callback
        view.add_item(scan_btn)
        view.add_item(dismiss_btn)

        prompt = await message.channel.send("Spotted a shard screen. Scan it for counts?", view=view)
        self._live_views[prompt.id] = view

        async def _drop():
            try:
                await asyncio.sleep((view.timeout or 300) + 5)
            except Exception:
                pass
            self._live_views.pop(prompt.id, None)

        asyncio.create_task(_drop())

    # ---------- OCR DIAGNOSTICS ----------
    @commands.command(name="ocrdebug")
    @commands.guild_only()
    async def ocr_debug_cmd(self, ctx: commands.Context):
        if not self._ocr_debug_enabled:
            await ctx.reply("OCR debug command is disabled. Ask an admin to enable ENABLE_OCR_DEBUG.", mention_author=False)
            return

        member = ctx.author if isinstance(ctx.author, discord.Member) else None
        if member is None:
            await ctx.reply("Guild-only command.", mention_author=False)
            return

        staff_roles = getattr(self.cfg, "roles_staff_override", [])
        perms = member.guild_permissions
        if not (perms.manage_guild or perms.administrator or _has_any_role(member, staff_roles)):
            await ctx.reply("You need Manage Server or a staff override role to run this.", mention_author=False)
            return

        chan_name = getattr(ctx.channel, "name", None) or getattr(ctx.channel, "id", "?")
        log.info(
            "[ocrdebug] invoked by %s (%s) in %s", str(ctx.author), getattr(ctx.author, "id", "?"), chan_name
        )

        try:
            data = await self._resolve_debug_image_bytes(ctx)
        except Exception:
            log.exception("[ocrdebug] failed while resolving an image source")
            await ctx.reply(
                "OCR debug failed to load an image. Attach a shard screenshot or reply to one and try again.",
                mention_author=False,
            )
            return

        if not data:
            await ctx.reply(
                "No image found. Attach a shard screenshot, reply to one, or rerun soon after scanning an image.",
                mention_author=False,
            )
            return

        try:
            await ctx.typing()
        except Exception:
            pass

        bundle = await asyncio.to_thread(collect_debug_bundle, data, 8)
        if not bundle:
            await ctx.reply("OCR pipeline is unavailable or failed to process the image.", mention_author=False)
            return

        counts_line = self._fmt_counts_line(bundle.counts)
        embed = discord.Embed(
            title="OCR Debug",
            description=(
                f"ROI ratio **{bundle.ratio:.2f}** · bands detected **{max(bundle.score, 0)}/5**\n"
                f"Counts → {counts_line}"
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.now(UTC),
        )

        files: List[discord.File] = []
        for band in bundle.bands:
            label = band.shard.value.title()
            text_raw = band.text or ""
            safe_text = text_raw.replace("`", "\`") or "∅"
            conf_display = "n/a" if band.conf < 0 else f"{band.conf:.1f}"
            oem_display = "—" if band.oem < 0 else str(band.oem)
            psm_display = "—" if band.psm < 0 else str(band.psm)
            mode = "fallback" if band.aggressive else "primary"
            cfg_summary = band.config_summary or "—"
            embed.add_field(
                name=f"{label} ({band.width}×{band.height})",
                value=(
                    f"Mode: **{mode}** · band #{band.band_index + 1}\n"
                    f"Processed: `{band.processed_label}` · OEM/PSM: `{oem_display}/{psm_display}`\n"
                    f"Config: `{cfg_summary}`\n"
                    f"Raw: `{safe_text}` (conf {conf_display})"
                ),
                inline=False,
            )

            roi_filename = f"roi_{band.band_index + 1}_{band.shard.value}.png"
            prep_filename = f"prep_{band.band_index + 1}_{band.shard.value}.png"
            if band.raw_bytes:
                files.append(discord.File(io.BytesIO(band.raw_bytes), filename=roi_filename))
            if band.processed_bytes:
                files.append(discord.File(io.BytesIO(band.processed_bytes), filename=prep_filename))

        await ctx.reply(embed=embed, files=files or None, mention_author=False)

    @commands.command(name="ocr")
    async def ocr_cmd(self, ctx: commands.Context, sub: Optional[str] = None):
        """
        Staff diagnostics:
          • !ocr info      → show OCR versions
          • !ocr selftest  → run '12345' smoke test
        """
        if not _has_any_role(ctx.author, getattr(self.cfg, "roles_staff_override", [])):
            await ctx.reply("Staff only.", mention_author=False)
            return

        s = (sub or "").strip().lower()
        if s in ("info", "ver", "version"):
            info = ocr_runtime_info()
            if not info:
                await ctx.reply("OCR runtime info unavailable (pytesseract/Pillow not importable).", mention_author=False)
                return
            langs = info.get("tesseract_languages") or "—"
            await ctx.reply(
                f"Tesseract lib: **{info.get('tesseract_version','?')}** | CLI: **{info.get('tesseract_cli_version','?')}**\n"
                f"pytesseract: **{info.get('pytesseract_version','?')}** | Pillow: **{info.get('pillow_version','?')}**\n"
                f"Languages: `{langs}`",
                mention_author=False,
            )
            return

        if s in ("selftest", "test"):
            t0 = time.perf_counter()
            ok, text = ocr_smoke_test()
            ms = int((time.perf_counter() - t0) * 1000)
            status = "PASS ✅" if ok else "FAIL ❌"
            await ctx.reply(
                f"OCR self-test: **{status}** in **{ms} ms**. Read: `{text or '∅'}` (expected `12345`).",
                mention_author=False,
            )
            return

        await ctx.reply("Usage: `!ocr info` or `!ocr selftest`.", mention_author=False)

    # ---------- COMMANDS ----------
    @commands.command(name="shards")
    async def shards_cmd(self, ctx: commands.Context, sub: Optional[str] = None, *, tail: Optional[str] = None):
        if not isinstance(ctx.channel, discord.Thread) or not self._is_shard_thread(ctx.channel):
            await ctx.reply("This command only works in your clan’s shard thread.")
            return

        sub = (sub or "").lower()
        if sub in {"", "help"}:
            await self._cmd_shards_help(ctx)
            return
        if sub == "set":
            await self._cmd_shards_set(ctx, tail)
            return
        await ctx.reply("Unknown subcommand. Try `!shards help`.")

    async def _cmd_shards_help(self, ctx: commands.Context):
        text = (
            "**Shard & Mercy — Quick Guide**\n"
            "Post a shard screenshot and press **Scan Image**, or type `!shards set` to enter counts for 🟩Myst 🟦Anc 🟪Void 🟥Pri 🟨Sac.\n"
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
                await ctx.reply("You need a staff role to manage data for others.")
                return
            if ctx.message.mentions:
                target = ctx.message.mentions[0]

        view = discord.ui.View(timeout=60)
        btn = discord.ui.Button(label="Open Set Shard Counts", style=discord.ButtonStyle.primary)

        async def _open(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                await inter.response.send_message("This button is not for you.", ephemeral=True)
                return

            modal = SetCountsModal(prefill=None)  # manual
            await inter.response.send_modal(modal)
            try:
                await modal.wait()
            except Exception:
                pass
            try:
                counts = modal.parse_counts()
            except Exception:
                counts = {}

            if not any(counts.values()):
                await inter.followup.send("No numbers provided.", ephemeral=True)
                return

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
            await self._cmd_addpulls(ctx, tail)
            return
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
            SA.append_events(
                [
                    {
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
                    }
                ]
            )
            await self._refresh_summary_for_clan(self._clan_tag_for_thread(ctx.channel.id))
            await ctx.reply("Pulls recorded. Summary updated.")
            return

        # Step 3: rarities (batch-aware)
        rar_modal = AddPullsRarities(shard, N)

        v = discord.ui.View(timeout=60)
        open_btn = discord.ui.Button(label="Open rarity form", style=discord.ButtonStyle.primary)

        async def _open2(i: discord.Interaction):
            if i.user.id != ctx.author.id:
                await i.response.send_message("Not for you.", ephemeral=True)
                return
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
        rows.append(
            {
                **base,
                "type": "pull",
                "rarity": "",
                "qty": N,
                "note": "batch",
                "guaranteed_flag": False,
                "extra_legendary_flag": False,
                "index_in_batch": "",
                "resets_pity": False,
            }
        )

        guar = bool(data.get("guaranteed", False))
        extra = bool(data.get("extra", False))

        if shard in (ShardType.ANCIENT, ShardType.VOID):
            if data.get("epic", False):
                rows.append(
                    {
                        **base,
                        "type": "epic",
                        "rarity": "epic",
                        "qty": 1,
                        "note": "",
                        "guaranteed_flag": False,
                        "extra_legendary_flag": False,
                        "index_in_batch": N - int(data.get("epic_left", 0)),
                        "resets_pity": True,
                    }
                )
            if data.get("legendary", False):
                rows.append(
                    {
                        **base,
                        "type": "legendary",
                        "rarity": "legendary",
                        "qty": 1,
                        "note": "guaranteed" if guar else ("extra" if extra else ""),
                        "guaranteed_flag": guar,
                        "extra_legendary_flag": extra,
                        "index_in_batch": N - int(data.get("legendary_left", 0)),
                        "resets_pity": not (guar or extra),
                    }
                )
        elif shard == ShardType.SACRED:
            if data.get("legendary", False):
                rows.append(
                    {
                        **base,
                        "type": "legendary",
                        "rarity": "legendary",
                        "qty": 1,
                        "note": "guaranteed" if guar else ("extra" if extra else ""),
                        "guaranteed_flag": guar,
                        "extra_legendary_flag": extra,
                        "index_in_batch": N - int(data.get("legendary_left", 0)),
                        "resets_pity": not (guar or extra),
                    }
                )
        elif shard == ShardType.PRIMAL:
            if data.get("legendary", False):
                rows.append(
                    {
                        **base,
                        "type": "legendary",
                        "rarity": "legendary",
                        "qty": 1,
                        "note": "guaranteed" if guar else ("extra" if extra else ""),
                        "guaranteed_flag": guar,
                        "extra_legendary_flag": extra,
                        "index_in_batch": N - int(data.get("legendary_left", 0)),
                        "resets_pity": not (guar or extra),
                    }
                )
            if data.get("mythical", False):
                rows.append(
                    {
                        **base,
                        "type": "mythical",
                        "rarity": "mythical",
                        "qty": 1,
                        "note": "guaranteed" if guar else ("extra" if extra else ""),
                        "guaranteed_flag": guar,
                        "extra_legendary_flag": extra,
                        "index_in_batch": N - int(data.get("mythical_left", 0)),
                        "resets_pity": not (guar or extra),
                    }
                )

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

        # TODO: plug in real Sheets aggregation when ready
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


async def setup(bot: commands.Bot):
    await bot.add_cog(ShardsCog(bot))
