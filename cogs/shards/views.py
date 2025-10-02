from __future__ import annotations
from typing import Dict, Optional, Tuple
import discord

from .constants import ShardType

# ------------- Set Counts Modal -------------

class SetCountsModal(discord.ui.Modal):
    def __init__(self, *, title: str = "Set Shard Counts", prefill: Optional[Dict[ShardType, int]] = None):
        super().__init__(title=title, timeout=180)
        pre = prefill or {}
        # Order: 🟩 Myst, 🟦 Anc, 🟪 Void, 🟥 Pri, 🟨 Sac
        self.mys = discord.ui.TextInput(label="🟩 Mystery", style=discord.TextStyle.short, default=str(pre.get(ShardType.MYSTERY, "")), required=False)
        self.anc = discord.ui.TextInput(label="🟦 Ancient", style=discord.TextStyle.short, default=str(pre.get(ShardType.ANCIENT, "")), required=False)
        self.void = discord.ui.TextInput(label="🟪 Void",    style=discord.TextStyle.short, default=str(pre.get(ShardType.VOID, "")), required=False)
        self.pri = discord.ui.TextInput(label="🟥 Primal",  style=discord.TextStyle.short, default=str(pre.get(ShardType.PRIMAL, "")), required=False)
        self.sac = discord.ui.TextInput(label="🟨 Sacred",  style=discord.TextStyle.short, default=str(pre.get(ShardType.SACRED, "")), required=False)
        for comp in (self.mys, self.anc, self.void, self.pri, self.sac):
            self.add_item(comp)

    def parse_counts(self) -> Dict[ShardType, int]:
        def num(txt: str) -> int:
            digits = "".join(ch for ch in (txt or "") if ch.isdigit())
            return int(digits) if digits else 0
        return {
            ShardType.MYSTERY: num(self.mys.value),
            ShardType.ANCIENT: num(self.anc.value),
            ShardType.VOID:    num(self.void.value),
            ShardType.PRIMAL:  num(self.pri.value),
            ShardType.SACRED:  num(self.sac.value),
        }

# ------------- Add Pulls (batch-aware) -------------

class AddPullsStart(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id
        for st, label in [
            (ShardType.ANCIENT, "🟦 Ancient"),
            (ShardType.VOID,    "🟪 Void"),
            (ShardType.SACRED,  "🟨 Sacred"),
            (ShardType.PRIMAL,  "🟥 Primal"),
            (ShardType.MYSTERY, "🟩 Mystery"),
        ]:
            self.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.primary, custom_id=f"addpulls:shard:{st.value}"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

class AddPullsCount(discord.ui.Modal):
    def __init__(self, shard: ShardType):
        super().__init__(title=f"Add Pulls — {shard.value.title()}", timeout=180)
        self.shard = shard
        self.count_inp = discord.ui.TextInput(label="How many pulls?", placeholder="1 or 10 or any whole number", style=discord.TextStyle.short)
        self.add_item(self.count_inp)

    def count(self) -> int:
        raw = (self.count_inp.value or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        return max(1, int(digits or "1"))

class AddPullsRarities(discord.ui.Modal):
    """
    Batch-aware: ask which rarities hit, and 'pulls left after last' per track.
    """
    def __init__(self, shard: ShardType, batch_n: int):
        super().__init__(title=f"Rarities — {shard.value.title()}", timeout=180)
        self.shard = shard
        self.batch_n = batch_n

        def add(label: str):
            ti = discord.ui.TextInput(label=label, style=discord.TextStyle.short, required=False)
            self.add_item(ti)
            return ti

        if shard in (ShardType.ANCIENT, ShardType.VOID):
            self.epic = add("Epic this batch? (yes/no)")
            self.epic_left = add("Pulls left after last Epic (0..N-1)")
            self.leg = add("Legendary this batch? (yes/no)")
            self.leg_left = add("Pulls left after last Legendary (0..N-1)")
            self.flags = add("Flags: guaranteed, extra (comma sep; optional)")
        elif shard == ShardType.SACRED:
            self.leg = add("Legendary this batch? (yes/no)")
            self.leg_left = add("Pulls left after last Legendary (0..N-1)")
            self.flags = add("Flags: guaranteed, extra (comma sep; optional)")
        elif shard == ShardType.PRIMAL:
            self.leg = add("Legendary this batch? (yes/no)")
            self.leg_left = add("Pulls left after last Legendary (0..N-1)")
            self.myth = add("Mythical this batch? (yes/no)")
            self.myth_left = add("Pulls left after last Mythical (0..N-1)")
            self.flags = add("Flags: guaranteed, extra (comma sep; optional)")

    @staticmethod
    def _yn(s: Optional[str]) -> bool:
        return (s or "").strip().lower() in {"y","yes","true","1"}

    @staticmethod
    def _num(s: Optional[str], upper: int) -> int:
        digits = "".join(ch for ch in (s or "") if ch.isdigit())
        val = int(digits) if digits else 0
        return max(0, min(val, max(0, upper-1)))

    @staticmethod
    def _flags(s: Optional[str]) -> tuple[bool,bool]:
        parts = [p.strip().lower() for p in (s or "").split(",") if p.strip()]
        return ("guaranteed" in parts, "extra" in parts)

    def parse(self) -> Dict[str, int | bool]:
        N = self.batch_n
        out: Dict[str, int | bool] = {}
        if self.shard in (ShardType.ANCIENT, ShardType.VOID):
            out["epic"] = self._yn(self.epic.value)
            out["epic_left"] = self._num(self.epic_left.value, N)
            out["legendary"] = self._yn(self.leg.value)
            out["legendary_left"] = self._num(self.leg_left.value, N)
            g,e = self._flags(self.flags.value)
            out["guaranteed"], out["extra"] = g, e
        elif self.shard == ShardType.SACRED:
            out["legendary"] = self._yn(self.leg.value)
            out["legendary_left"] = self._num(self.leg_left.value, N)
            g,e = self._flags(self.flags.value)
            out["guaranteed"], out["extra"] = g, e
        elif self.shard == ShardType.PRIMAL:
            out["legendary"] = self._yn(self.leg.value)
            out["legendary_left"] = self._num(self.leg_left.value, N)
            out["mythical"] = self._yn(self.myth.value)
            out["mythical_left"] = self._num(self.myth_left.value, N)
            g,e = self._flags(self.flags.value)
            out["guaranteed"], out["extra"] = g, e
        return out
