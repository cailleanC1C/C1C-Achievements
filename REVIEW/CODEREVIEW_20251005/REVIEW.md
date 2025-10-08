# Review — C1C Achievement Bot

## Executive Summary — **Yellow**
Core claim flows and Guardian Knight tooling are in place, but two robustness issues keep the bot fragile in production: config reloads block the gateway thread on every Sheets call, and shard summary updates crash once the worksheet has data. Monitoring accuracy also suffers because the digest mixes runtime/config readiness. Address the blocking I/O first to keep the bot responsive under slow Sheets conditions; the remaining fixes are straightforward.

## Findings by Severity & Category

### High Severity
- **F-01 — Robustness:** `load_config()` runs synchronously inside async contexts (`!reloadconfig`, auto-refresh, boot backoff, CoreOps reload), freezing the event loop during Google Sheets/Excel I/O.【F:c1c_claims_appreciation.py†L213-L325】【F:c1c_claims_appreciation.py†L1545-L1554】【F:c1c_claims_appreciation.py†L1283-L1292】【F:cogs/ops.py†L214-L301】  
  ↳ *Fix:* introduce `load_config_async()` that offloads to `run_in_executor`/`asyncio.to_thread`, then `await` it from every caller (see F-01 diff).

### Medium Severity
- **F-02 — Correctness:** `claims/ops.build_digest_line` overwrites the runtime readiness flag with the config readiness flag, so the digest shows the same value twice and can wrongly report `ready:False` while the bot is actually ready.【F:claims/ops.py†L86-L111】  
  ↳ *Fix:* keep separate variables for runtime and config readiness and format both explicitly.
- **F-03 — Correctness:** `cogs/shards/sheets_adapter.set_summary_msg` always issues an empty `append_row` when the worksheet already has rows, triggering gspread’s “Row values must not be empty” error and preventing subsequent summary updates.【F:cogs/shards/sheets_adapter.py†L139-L165】  
  ↳ *Fix:* only append the header when the sheet is empty; otherwise update the existing row and append just the payload.

## Automated Checks
- `ruff check .` — ❌ (56 style errors; see `REVIEW/LINT_REPORT.md`).【fa0609†L1-L118】
- `mypy .` — ❌ (module name collision for `core/prefix.py`; see `REVIEW/TYPECHECK_REPORT.md`).【53a2f6†L1-L5】

## Artifacts
- Detailed findings: `REVIEW/FINDINGS.md`
- Test plan: `REVIEW/TESTPLAN.md`
- Threat model: `REVIEW/THREATS.md`
- Hotspots: `REVIEW/HOTSPOTS.csv`
- Perf notes: `REVIEW/PERF_NOTES.md`
- Lint report: `REVIEW/LINT_REPORT.md`
- Type-check report: `REVIEW/TYPECHECK_REPORT.md`
- Architecture map: `REVIEW/ARCH_MAP.md`
- TODO tracker: `REVIEW/TODOS.md`
