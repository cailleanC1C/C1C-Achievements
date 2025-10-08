# DEVELOPMENT — C1C Achievement Bot

This document is for developers and operators. It explains the architecture, where commands live, how to extend the bot safely, and the rules that keep our quota happy.

---

## Architecture (current)

* **Service bootstrap**: `c1c_claims_appreciation.py` — bot init, Flask keep-alive, config loader (Sheets or local), watchdog/health wiring, Cog registration.
* **Cogs (UI only)**: `cogs/` — admin/CoreOps commands. These call into `claims/*`.

  * `cogs/ops.py` (registers `!sc health|digest|reload|checksheet|env`)
* **CoreOps renderers & helpers**: `claims/`

  * `ops.py` (embeds for health/digest/env/checksheet/reload)
  * `help.py` (topic pages for `help {topic}` incl. `claim/claims/gk`, `health/digest/reload/checksheet/env`, previews)
  * `middleware/coreops_prefix.py` (prefix router: handles `!sc …` and bare-command picker)
* **Config I/O (in main)**: `c1c_claims_appreciation.py` loads **General, Categories, Achievements, Levels, Reasons** (Sheets or local XLSX).
  *(There is no separate `claims/sheets.py` file yet; Sheets access lives in the entry module.)*

**Invariants**

* Cogs are **UI only**; rendering lives in `claims/ops.py`.
* Role-based appreciation is **whitelisted via Sheets** (Achievements/Levels). No whitelist → no public post.
* Audit logging fires **only** for roles explicitly configured to log.
* Bare CoreOps commands prompt for a **scoped prefix**; `!ping` stays **global** and **react-only**.
* Grouping window merges rapid grants into **one combined appreciation** to prevent spam.

---

## Command → File map (source of truth)

| Command          | Who      | File                                  | Symbol(s)           | Anchor (find this line)                |
| ---------------- | -------- | ------------------------------------- | ------------------- | -------------------------------------- |
| `!sc health`     | Admins   | `cogs/ops.py`                         | `OpsCog.health`     | `@commands.command(name="health")`     |
| `!sc digest`     | Admins   | `cogs/ops.py`                         | `OpsCog.digest`     | `@commands.command(name="digest")`     |
| `!sc reload`     | Admins   | `cogs/ops.py`                         | `OpsCog.reload`     | `@commands.command(name="reload")`     |
| `!sc checksheet` | Admins   | `cogs/ops.py`                         | `OpsCog.checksheet` | `@commands.command(name="checksheet")` |
| `!sc env`        | Admins   | `cogs/ops.py`                         | `OpsCog.env`        | `@commands.command(name="env")`        |
| `!help {topic}`  | Everyone | `claims/help.py`                      | `build_help_embed`  | `def build_help_embed(`                |
| (router) `!sc …` | Everyone | `claims/middleware/coreops_prefix.py` | `CoreOpsPrefixCog`  | `class CoreOpsPrefixCog(`              |
| Global `!ping`   | Everyone | *(main)*                              | `ping` (react-only) | *(keep as one-liner react, no spam)*   |

> Admin preview helpers shown in README (`!testach`, `!testlevel`) are implemented as help topics + internal preview paths in this repo. If/when promoted to commands, add rows here with file + anchors.

---

## Adding a new module (safe pattern)

1. Put logic in `claims/<module>.py` with a minimal public API (no side effects at import).
2. Expose a Cog in `cogs/<name>.py` that calls the module’s API. Cogs are UI only.
3. Render admin/user output via `claims/ops.py` (or a sibling renderer) to keep style consistent.
4. Read config once in the entry module; pass data into modules via explicit parameters. Avoid ad-hoc reads inside buttons.
5. Keep **grouping and audit** behavior centralized—don’t reimplement per feature.

---

## Patch protocol (exact)

When proposing code changes, provide:

* **File & location** (exact path)
* **Find this line** anchor
* **BEFORE / AFTER** blocks (copy-pasteable)
* **Call out every added/removed line** (no fuzzy steps)
* **One-line “Why”** (what the change fixes or enables)
* **No +/- diff fences**; only full blocks suitable for paste-over

---

## Quota guardrails

* **Grouping window** reduces message volume in #levels; prefer tuning that over posting per-grant.
* **On-demand refresh** (`!sc reload`) instead of frequent background pulls.
* Google Sheets: **read-only** scope; prefer **batch reads** of whole tabs over many small calls.
* Health/digest should not trigger extra Sheets reads beyond already loaded config.

---

## Roadmap (near-term)

* Move Sheets I/O from entry module into `claims/sheets.py` for parity with other bots.
* Promote preview flows to explicit commands if needed (`!testach`, `!testlevel`) and document here.
* Add per-category message templates (opt-in) and multi-language toggles via Sheets.
* Unify `render.yaml` start command with the actual entry file (`c1c_claims_appreciation.py`).

---

## Runbooks (short)

* **After deploy**: `!sc health` (version, source, counts) → `!sc checksheet` (confirm Google Sheet vs local) → run a preview path (see README) to verify embeds.
* **If appreciation posts don’t appear**: confirm role is whitelisted in **Achievements/Levels** → check target channel ID in **General** → `!sc reload`.
* **If posts are too noisy**: increase `group_window_seconds` in **General**.
* **If GK flow fails**: verify `guardian_knights_role_id` and the claims thread/channel IDs in **General**.
* **If audit is empty**: ensure the role is flagged for logging in **Achievements/Levels**.

---

## Notes for future contributors

* Keep Cogs **thin**; put formatting in `claims/ops.py` and data in the entry module or a future `claims/sheets.py`.
* Don’t scatter Sheets reads across buttons/interactions. Load once; reuse.
* Preserve the CoreOps prefix behavior and bare-command picker. `!ping` stays react-only.
