# C1C Achievement Bot v1.0.3

A Discord bot for the C1C cluster that **celebrates member achievements and milestones**.
It automatically posts **warm, styled shout-outs** when specific roles are granted, keeps #levels tidy by grouping multiple unlocks, and gives Guardian Knights tools to process screenshot claims without flooding chat.

---

## Features

* 🎉 **Smart appreciation messages** when achievement or level roles are granted
* 🧩 **Grouping logic** to combine bursts of unlocks into one neat post
* 🛡 **Guardian Knight review flow** for screenshot-based claims
* 📜 **Audit-log entries** only for roles that matter
* 🧪 **Preview/testing tools** for admins before going cluster-wide
* 📊 **Google Sheets configuration** (Achievements, Levels, Categories, Reasons, General)

--- 

## What’s new in v1.0.3

* **Shared OpsCommands** introduced: all bots now use scoped prefixes for health, digest, reload, etc.
* **Appreciation logic refined**: multiple role grants in a short window become one combined message.
* **Guardian Knight review flow**: screenshot claims thread + standardized “Reasons” for approvals/denials.
* **Audit filtering**: only configured role names show up in the audit channel.
* **Preview commands**: admins can test how appreciation posts will look before rollout.

---

## Quick start (admins)

1. **Invite the bot** to your server with the usual Discord bot link.
2. **Set up the Google Sheet** with the required tabs (General, Categories, Achievements, Levels, Reasons).
3. **Configure IDs** in the General sheet (levels channel, claims thread, audit log, Guardian Knights role).
4. **Grant Guardian Knights** their role so they can process claims.
5. **Test** using `!testach` or `!testlevel` to make sure appreciation posts look right.

---

## Shared OpsCommands

Like the Reminder Bot, this bot uses the **shared CoreOps model**.
All bots share the same admin commands (`health`, `digest`, `reload`, etc.), but each listens only to its own prefix:

* **Achievement Bot (Scribe):** `!sc health`, `!sc digest`, …
* **Reminder Bot:** `!rem …`
* **Welcome Crew:** `!wc …`
* **Matchmaker:** `!mm …`

Typing a bare command like `!health` prompts you to pick which bot you mean.
`!ping` remains global (one-liner react only).

---

## Commands

### Admin / Ops (scoped to `!sc`)

* `!sc health` — Show full health info (version, config source, table counts, status line).
* `!sc digest` — Quick one-liner health digest.
* `!sc reload` — Reload configuration from Sheets or local file.
* `!sc checksheet` — Show which Google Sheet (or local file) is active.
* `!sc env` — Show key environment variables (secrets redacted).
* `!ocr info` — Print Tesseract / pytesseract / Pillow versions plus installed languages.
* `!ocr selftest` — Render “12345”, OCR it, and report the raw text + latency.
* `!ocrdebug` — (feature toggled, staff-only) attach a shard screenshot to see the band crops, preprocessing, and raw OCR output.

### Guardian Knight & Claim Flow

* `!help claim` / `!help claims` — Help topics on how to post and review claims.
* `!help gk` — Guardian Knight help overview.

### Preview / Testing

* `!testach <key> [where]` — Preview an achievement appreciation post.
* `!testlevel [query] [where]` — Preview a level-up appreciation post.

### Global

* `!ping` — Quick alive check (react only).

---

## How it works

* Members earn roles for achievements, milestones, or special champion unlocks.
* The bot detects those roles and posts a **celebratory message** in your levels channel.
* If several roles are granted close together, the bot groups them into **one combined message**.
* Guardian Knights can review screenshot claims in a dedicated thread, approve/deny with reasons, and keep the process consistent.

---

## Troubleshooting

* **No messages appear:** check that the role is listed in the Achievements or Levels sheet.
* **Duplicate or missing posts:** adjust the grouping window in the General sheet.
* **Audit entries missing:** make sure the role name is flagged for logging in the sheet.
* **Guardian Knight commands not working:** confirm the correct role ID is set for Guardian Knights.
* **Still stuck?** Use `!sc health` to see if the bot can read your sheet and channels.

### Feature toggles

* `ENABLE_OCR_DEBUG` — defaults to `false`. When `true`, registers `!ocrdebug` for approved test guilds.
* `OCR_DEBUG_GUILD_IDS` — comma-separated guild IDs allowed to run `!ocrdebug` (e.g., `123,456`).

---

## Links
- `CHANGELOG` — daily consolidated changes  
- `CARVE_OUT_PLAN` — current scope and roadmap  
- `DEVELOPMENT.md` — architecture, adding modules, patch protocol, command map



Do you want me to move on and draft the **CHANGELOG.md** next in the same consistent style?
