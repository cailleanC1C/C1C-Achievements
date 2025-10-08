# Ready-to-Implement Gate

**Status:** No

**Blocking prerequisites:**
1. Publish feature issues for the manual-first button and emoji migration with acceptance criteria, Discord test steps, non-goals, and rollout notes.【F:ISSUE_AUDIT.md†L5-L14】
2. Decide on/collect the custom emoji IDs for each shard and commit the shared mapping file so engineering can wire it in without guessing.【F:EMOJI_AUDIT.md†L3-L24】
3. Agree on the UX for manual entry when no attachment is present (public prompt copy, whether to show scan button disabled, etc.) before coding the listener change.【F:SPEC_DIFF.md†L11-L18】【F:UI_FLOW_MAP.md†L6-L13】
