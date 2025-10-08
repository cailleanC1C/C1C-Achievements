# Test Plan

| Scenario | Steps | Expected |
| --- | --- | --- |
| Bootstraps config on cold start | Set valid `CONFIG_SHEET_ID` + creds, start bot | Bot logs `[config]` ready, CoreOps `health` shows counts > 0 |
| Prefix guard parity | As non-staff, run `!health` → expect prefix picker; run `!sc health` → expect denial (staff only). As staff, `!health` succeeds. | Non-staff receive picker text; staff get embed |
| Claim auto-grant | Post qualifying screenshot in claims thread for AUTO_GRANT role | Bot opens picker → select role → role assigned, claim embed posted to #levels within 60s |
| Claim GK review | Post screenshot for review-mode role | Bot pings GK, GK approves, role assigned, audit log entry created |
| Multi-claim grouping | Grant two achievements to same user within 60s | Single grouped embed in #levels listing both roles, audit shows `praise_posted` with `items=2` |
| Group flush cancel | Remove user from guild before flush | Pending entry cleared (no message posted) |
| Level-up watcher | Simulate bot message “User has reached Level X” | Bot posts level embed, audit indicates `level_praise` |
| Sheets outage during reload | Force `load_config` to raise (e.g., revoke creds) then run `!reloadconfig` | Command returns error, previous config remains active, audit logs failure |
| Shards OCR happy path | Post shard screenshot in clan thread, click Scan → Use counts | OCR preview shows counts, saving updates summary message |
| Shards OCR manual entry | Trigger scan, choose manual entry, submit counts | Counts saved and summary refreshed |
| CoreOps env/checksheet | Run `!sc env` / `!sc checksheet` | Embeds display sanitized env + sheet headers |
| Auto-refresh | Set `CONFIG_AUTO_REFRESH_MINUTES=1`, update sheet | Config reloads off-thread without blocking commands, new data reflected |
