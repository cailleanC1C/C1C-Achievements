# Sheets broker acceptance checklist

- [x] One process-wide Google Sheets read budget is installed before Achievements helpers use gspread.
- [x] Production default is 6 sustained reads per minute via `SHEETS_READ_BUDGET_RPM`.
- [x] Read-only config and read/write HelpCommands clients never share cached gspread handles.
- [x] Config values use a 10-minute fresh cache with a 4-hour stale fallback.
- [x] HelpCommands value reads remain fresh-required before seeding/upserting.
- [x] Concurrent identical reads coalesce through one in-flight loader.
- [x] 429 / `RESOURCE_EXHAUSTED` retry and cooldown are centralized in the broker.
- [x] Successful worksheet mutations invalidate matching cached values.
- [x] Local Excel fallback remains available when gspread is intentionally absent.
- [x] No Google Sheets data/config changes are required by this PR.
