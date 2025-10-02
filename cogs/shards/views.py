*** /dev/null
--- a/cogs/shards/views.py
@@
+from __future__ import annotations
+from typing import Dict, Optional, Tuple
+import discord
+from discord.ui import View, Button, Modal, InputText
+
+from .constants import ShardType, Rarity, DISPLAY_ORDER
+
+# ---------- Set Counts Modal ----------
+class SetCountsModal(Modal):
+    def __init__(self, *, title: str = "Set Shard Counts", prefill: Optional[Dict[ShardType,int]] = None):
+        super().__init__(title=title, timeout=180)
+        pre = prefill or {}
+        # Order: Myst, Anc, Void, Pri, Sac
+        self.add_item(InputText(label="🟩 Mystery", style=discord.InputTextStyle.short, value=str(pre.get(ShardType.MYSTERY, "")), required=False))
+        self.add_item(InputText(label="🟦 Ancient", style=discord.InputTextStyle.short, value=str(pre.get(ShardType.ANCIENT, "")), required=False))
+        self.add_item(InputText(label="🟪 Void",    style=discord.InputTextStyle.short, value=str(pre.get(ShardType.VOID, "")), required=False))
+        self.add_item(InputText(label="🟥 Primal",  style=discord.InputTextStyle.short, value=str(pre.get(ShardType.PRIMAL, "")), required=False))
+        self.add_item(InputText(label="🟨 Sacred",  style=discord.InputTextStyle.short, value=str(pre.get(ShardType.SACRED, "")), required=False))
+
+    def parse_counts(self) -> Dict[ShardType,int]:
+        vals = {}
+        labels = [ShardType.MYSTERY, ShardType.ANCIENT, ShardType.VOID, ShardType.PRIMAL, ShardType.SACRED]
+        for comp, st in zip(self.children, labels):
+            raw = comp.value.strip() if isinstance(comp, InputText) and comp.value else ""
+            if raw == "":
+                continue
+            n = max(0, int("".join(ch for ch in raw if ch.isdigit())))
+            vals[st] = n
+        return vals
+
+# ---------- Add Pulls Flow ----------
+class AddPullsStart(View):
+    def __init__(self, author_id: int):
+        super().__init__(timeout=120)
+        self.author_id = author_id
+        for st, label in [
+            (ShardType.ANCIENT, "🟦 Ancient"),
+            (ShardType.VOID,    "🟪 Void"),
+            (ShardType.SACRED,  "🟨 Sacred"),
+            (ShardType.PRIMAL,  "🟥 Primal"),
+            (ShardType.MYSTERY, "🟩 Mystery"),
+        ]:
+            self.add_item(Button(label=label, style=discord.ButtonStyle.primary, custom_id=f"addpulls:shard:{st.value}"))
+
+    async def interaction_check(self, interaction: discord.Interaction) -> bool:
+        return interaction.user.id == self.author_id
+
+class AddPullsCount(Modal):
+    def __init__(self, shard: ShardType):
+        super().__init__(title=f"Add Pulls — {shard.value.title()}", timeout=180)
+        self.shard = shard
+        self.add_item(InputText(label="How many pulls?", placeholder="1 or 10 or any whole number", style=discord.InputTextStyle.short))
+
+    def count(self) -> int:
+        raw = self.children[0].value.strip()
+        n = max(1, int("".join(ch for ch in raw if ch.isdigit())))
+        return n
+
+class AddPullsRarities(Modal):
+    """
+    Batch-aware: ask which rarities hit, and 'pulls left after last' per track.
+    """
+    def __init__(self, shard: ShardType, batch_n: int):
+        super().__init__(title=f"Rarities — {shard.value.title()}", timeout=180)
+        self.shard = shard
+        self.batch_n = batch_n
+        # Fields are free-form; Validate in handler.
+        # We keep it simple: 'Epic? yes/no' + 'Pulls left after last' per rarity, depending on shard.
+        if shard in (ShardType.ANCIENT, ShardType.VOID):
+            self.add_item(InputText(label="Epic this batch? (yes/no)", required=False))
+            self.add_item(InputText(label="Pulls left after last Epic (0..N-1)", required=False))
+            self.add_item(InputText(label="Legendary this batch? (yes/no)", required=False))
+            self.add_item(InputText(label="Pulls left after last Legendary (0..N-1)", required=False))
+            self.add_item(InputText(label="Flags: guaranteed, extra (comma sep; optional)", required=False))
+        elif shard == ShardType.SACRED:
+            self.add_item(InputText(label="Legendary this batch? (yes/no)", required=False))
+            self.add_item(InputText(label="Pulls left after last Legendary (0..N-1)", required=False))
+            self.add_item(InputText(label="Flags: guaranteed, extra (comma sep; optional)", required=False))
+        elif shard == ShardType.PRIMAL:
+            self.add_item(InputText(label="Legendary this batch? (yes/no)", required=False))
+            self.add_item(InputText(label="Pulls left after last Legendary (0..N-1)", required=False))
+            self.add_item(InputText(label="Mythical this batch? (yes/no)", required=False))
+            self.add_item(InputText(label="Pulls left after last Mythical (0..N-1)", required=False))
+            self.add_item(InputText(label="Flags: guaranteed, extra (comma sep; optional)", required=False))
+        else:
+            # Mystery: no rarities
+            pass
+
+    @staticmethod
+    def _yn(s: Optional[str]) -> bool:
+        if not s: return False
+        s = s.strip().lower()
+        return s in ("y","yes","true","1")
+
+    @staticmethod
+    def _num(s: Optional[str], upper: int) -> int:
+        if not s: return 0
+        v = "".join(ch for ch in s if ch.isdigit())
+        return min(max(0, int(v or 0)), max(0, upper-1))
+
+    @staticmethod
+    def _flags(s: Optional[str]) -> Tuple[bool,bool]:
+        if not s: return (False, False)
+        parts = [p.strip().lower() for p in s.split(",")]
+        return ("guaranteed" in parts, "extra" in parts)
+
+    def parse(self) -> Dict[str, int|bool]:
+        out: Dict[str,int|bool] = {}
+        N = self.batch_n
+        i = 0
+        if self.shard in (ShardType.ANCIENT, ShardType.VOID):
+            epic = self._yn(self.children[i].value); i+=1
+            epic_left = self._num(self.children[i].value, N); i+=1
+            leg = self._yn(self.children[i].value); i+=1
+            leg_left = self._num(self.children[i].value, N); i+=1
+            guar, extra = self._flags(self.children[i].value); i+=1
+            out.update(dict(epic=epic, epic_left=epic_left, legendary=leg, legendary_left=leg_left, guaranteed=guar, extra=extra))
+        elif self.shard == ShardType.SACRED:
+            leg = self._yn(self.children[i].value); i+=1
+            leg_left = self._num(self.children[i].value, N); i+=1
+            guar, extra = self._flags(self.children[i].value); i+=1
+            out.update(dict(legendary=leg, legendary_left=leg_left, guaranteed=guar, extra=extra))
+        elif self.shard == ShardType.PRIMAL:
+            leg = self._yn(self.children[i].value); i+=1
+            leg_left = self._num(self.children[i].value, N); i+=1
+            myth = self._yn(self.children[i].value); i+=1
+            myth_left = self._num(self.children[i].value, N); i+=1
+            guar, extra = self._flags(self.children[i].value); i+=1
+            out.update(dict(legendary=leg, legendary_left=leg_left, mythical=myth, mythical_left=myth_left, guaranteed=guar, extra=extra))
+        else:
+            # Mystery: nothing
+            pass
+        return out
+
+# ---------- Pagination Buttons ----------
+class SummaryPager(View):
+    def __init__(self, page_index: int):
+        super().__init__(timeout=None)
+        self.page_index = page_index
+        self.add_item(Button(label="⏮ Prev", style=discord.ButtonStyle.secondary, custom_id="pager:prev"))
+        self.add_item(Button(label="Next ⏭", style=discord.ButtonStyle.secondary, custom_id="pager:next"))
+        self.add_item(Button(label="⟳ Refresh", style=discord.ButtonStyle.secondary, custom_id="pager:refresh"))
