"""Achievements bot helper package."""

# Install the quota boundary as soon as the Achievements package is imported so
# both the main config loader and help seeding share one process-wide budget.
# Keep the historical local-Excel fallback viable in environments where
# gspread is intentionally not installed.
try:
    from achievements.sheets_read_broker import (
        install_gspread_broker,
        sheets_broker_snapshot as _sheets_broker_snapshot,
    )
except ModuleNotFoundError as exc:
    if not str(getattr(exc, "name", "")).startswith("gspread"):
        raise

    def sheets_broker_snapshot() -> dict:
        return {"available": False}
else:
    install_gspread_broker()

    def sheets_broker_snapshot() -> dict:
        return {"available": True, **_sheets_broker_snapshot()}


__all__ = ["sheets_broker_snapshot"]
