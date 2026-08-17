"""Achievements bot helper package.

The Sheets quota boundary must be installed before existing gspread callers run,
but package import must not start background telemetry threads.  Telemetry is
therefore armed lazily on the already-brokered ``Client.open_by_key`` boundary
and starts only when this process actually begins using Google Sheets.
"""

from __future__ import annotations


# Keep the historical local-Excel fallback viable in environments where
# gspread is intentionally not installed.
try:
    from gspread.client import Client

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
    # The broker must exist before any existing Achievements gspread caller can
    # perform I/O.  This installer is idempotent.
    install_gspread_broker()

    def _install_lazy_telemetry_hook() -> None:
        current_open_by_key = Client.open_by_key
        if getattr(current_open_by_key, "__c1c_sheets_telemetry_hook__", False):
            return

        def open_by_key_with_telemetry(self, key, *args, **kwargs):
            # Import/start telemetry only when the process actually begins using
            # Google Sheets.  At this point the broker is already installed, so
            # telemetry can never race broker bootstrap during package import.
            from achievements.sheets_telemetry import start_sheets_telemetry

            start_sheets_telemetry()
            return current_open_by_key(self, key, *args, **kwargs)

        # Preserve the broker installation marker because install_gspread_broker
        # uses it to prevent duplicate monkey-patching.
        open_by_key_with_telemetry.__c1c_sheets_brokered__ = bool(
            getattr(current_open_by_key, "__c1c_sheets_brokered__", False)
        )
        open_by_key_with_telemetry.__c1c_sheets_telemetry_hook__ = True
        open_by_key_with_telemetry.__name__ = getattr(
            current_open_by_key, "__name__", "open_by_key"
        )
        open_by_key_with_telemetry.__doc__ = getattr(current_open_by_key, "__doc__", None)
        Client.open_by_key = open_by_key_with_telemetry

    _install_lazy_telemetry_hook()

    def sheets_broker_snapshot() -> dict:
        return {"available": True, **_sheets_broker_snapshot()}


__all__ = ["sheets_broker_snapshot"]
