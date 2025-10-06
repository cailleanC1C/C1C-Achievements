# Threat Model Snapshot

## Assets
- Discord guild integrity (roles, channels, audit history).
- Google Sheets configuration and shard data (service-account credentials).
- Bot tokens and service-account secrets stored in environment variables.

## Trust Boundaries
- Discord Gateway/API ↔ bot runtime.
- Bot runtime ↔ Google Sheets API via service account.
- Guardian Knights / staff interactions via privileged commands.

## Top Risks
1. **Credential leakage**: Service-account JSON or bot token logged/committed accidentally.
2. **Privilege escalation**: Non-staff invoking CoreOps commands without prefix guard or role checks.
3. **Inconsistent state**: Partial config reloads or blocking calls causing event loop stalls, leading to missed Discord events.
4. **Sheets abuse / rate limits**: High-frequency writes (shard logging) exhaust quota or fail mid-flight.

## Mitigations & Gaps
- Prefix guard exists, but ensure plain `!health`/`!reload` remain staff-only and log denials.
- Move Sheets/network I/O off the event loop and wrap in retries with backoff to avoid gateway stalls.
- Store secrets via environment variables only; avoid printing decoded JSON.
- Batch Sheets writes where possible and add bounded retry/jitter for append operations.
