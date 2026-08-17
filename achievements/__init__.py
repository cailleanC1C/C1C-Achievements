"""Achievements bot helper package."""

# Install the quota boundary as soon as the Achievements package is imported so
# both the main config loader and help seeding share one process-wide budget.
# Keep the historical local-Excel fallback viable in environments where
# gspread is intentionally not installed.
try:
    from achievements.sheets_read_broker import install_gspread_broker
except ModuleNotFoundError as exc:
    if not str(getattr(exc, "name", "")).startswith("gspread"):
        raise
else:
    install_gspread_broker()
