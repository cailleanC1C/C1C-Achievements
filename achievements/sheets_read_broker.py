"""Process-wide Google Sheets quota broker for C1C-Achievements.

Achievements has two synchronous gspread consumers: the normal read-only config
loader and the read/write HelpCommands seed path.  This module installs one
process-wide quota and value-cache boundary while keeping cached gspread handles
scoped to the client that created them, so credential scopes never bleed across
those two paths.
"""

from __future__ import annotations

import copy
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Hashable

from gspread.client import Client
from gspread.exceptions import WorksheetNotFound
from gspread.spreadsheet import Spreadsheet
from gspread.worksheet import Worksheet

log = logging.getLogger("c1c-claims.sheets.broker")


@dataclass(frozen=True)
class CachePolicy:
    fresh_seconds: float
    stale_seconds: float


HANDLE_POLICY = CachePolicy(fresh_seconds=30 * 60, stale_seconds=12 * 60 * 60)
CONFIG_DATA = CachePolicy(fresh_seconds=10 * 60, stale_seconds=4 * 60 * 60)
FRESH_REQUIRED = CachePolicy(fresh_seconds=0, stale_seconds=0)

_CONFIG_TABS = {"GENERAL", "CATEGORIES", "ACHIEVEMENTS", "LEVELS", "REASONS", "CONFIG"}


@dataclass
class _CacheEntry:
    value: Any
    loaded_at: float


@dataclass
class _Flight:
    event: threading.Event
    error: BaseException | None = None


class QuotaCooldownError(RuntimeError):
    """Raised without a physical call while an exhausted quota cools."""

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))
        super().__init__(
            f"429 Sheets quota cooldown active; retry after {self.retry_after_seconds:.1f}s"
        )


def is_rate_limited_error(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "429",
            "resource_exhausted",
            "resource exhausted",
            "quota",
            "read requests",
            "readrequestsperminuteperuser",
        )
    )


def _env_rpm(default: int = 6) -> int:
    raw = (os.getenv("SHEETS_READ_BUDGET_RPM") or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        log.warning("Invalid SHEETS_READ_BUDGET_RPM=%r; using %d", raw, default)
        return default


def _freeze(value: Any) -> Hashable:
    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return value
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    return repr(value)


def _sheet_id(spreadsheet: Any) -> str:
    return str(
        getattr(spreadsheet, "id", "")
        or getattr(spreadsheet, "spreadsheet_id", "")
        or "<unknown-workbook>"
    )


def _client_identity(client: Any) -> int:
    return id(client)


def _worksheet_identity(worksheet: Any) -> tuple[str, str]:
    spreadsheet_id = str(
        getattr(worksheet, "spreadsheet_id", "")
        or getattr(getattr(worksheet, "spreadsheet", None), "id", "")
        or "<unknown-workbook>"
    )
    worksheet_id = str(
        getattr(worksheet, "id", "")
        or getattr(worksheet, "_properties", {}).get("sheetId", "")
        or getattr(worksheet, "title", "")
        or "<unknown-worksheet>"
    )
    return spreadsheet_id, worksheet_id


def _worksheet_policy(worksheet: Any) -> CachePolicy:
    title = str(getattr(worksheet, "title", "") or "").strip().upper()
    return CONFIG_DATA if title in _CONFIG_TABS else FRESH_REQUIRED


class SheetsReadBroker:
    """Synchronous quota broker with caching, coalescing and cooldown."""

    def __init__(
        self,
        *,
        rpm: int | None = None,
        rate_window_seconds: float = 60.0,
        retry_attempts: int = 4,
        retry_base_seconds: float = 0.75,
        retry_cap_seconds: float = 8.0,
        exhausted_cooldown_seconds: float = 60.0,
    ) -> None:
        self.rpm = max(1, int(rpm or _env_rpm()))
        self.rate_window_seconds = max(0.001, float(rate_window_seconds))
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_base_seconds = max(0.0, float(retry_base_seconds))
        self.retry_cap_seconds = max(self.retry_base_seconds, float(retry_cap_seconds))
        self.exhausted_cooldown_seconds = max(0.0, float(exhausted_cooldown_seconds))

        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._cache: dict[Hashable, _CacheEntry] = {}
        self._inflight: dict[Hashable, _Flight] = {}

        # A quiet process may consume its small allocation as a startup burst;
        # sustained refill remains SHEETS_READ_BUDGET_RPM per minute.  This
        # avoids adding minute-long sleeps inside the synchronous Discord path.
        self._capacity = float(self.rpm)
        self._tokens = float(self.rpm)
        self._last_refill = time.monotonic()
        self._cooldown_until = 0.0

        self._physical_reads = 0
        self._physical_timestamps: list[float] = []
        self._cache_hits = 0
        self._stale_hits = 0
        self._misses = 0
        self._coalesced = 0
        self._rate_limits = 0
        self._retries = 0
        self._invalidations = 0

    @property
    def _refill_per_second(self) -> float:
        return float(self.rpm) / self.rate_window_seconds

    def _refill_locked(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_refill)
        if elapsed:
            self._tokens = min(
                self._capacity,
                self._tokens + elapsed * self._refill_per_second,
            )
            self._last_refill = now

    def _acquire_slot(self) -> None:
        with self._condition:
            while True:
                now = time.monotonic()
                if now < self._cooldown_until:
                    raise QuotaCooldownError(self._cooldown_until - now)

                self._refill_locked(now)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._physical_reads += 1
                    self._physical_timestamps.append(now)
                    cutoff = now - self.rate_window_seconds
                    self._physical_timestamps = [
                        ts for ts in self._physical_timestamps if ts >= cutoff
                    ]
                    return

                wait_for = (1.0 - self._tokens) / self._refill_per_second
                self._condition.wait(timeout=max(0.001, wait_for))

    def _load_with_retry(
        self,
        loader: Callable[[], Any],
        *,
        component: str,
        reason: str,
    ) -> Any:
        for attempt in range(1, self.retry_attempts + 1):
            self._acquire_slot()
            try:
                return loader()
            except BaseException as exc:
                if not is_rate_limited_error(exc):
                    raise

                with self._lock:
                    self._rate_limits += 1

                if attempt >= self.retry_attempts:
                    with self._condition:
                        self._cooldown_until = max(
                            self._cooldown_until,
                            time.monotonic() + self.exhausted_cooldown_seconds,
                        )
                        self._condition.notify_all()
                    raise

                with self._lock:
                    self._retries += 1
                delay = min(
                    self.retry_cap_seconds,
                    self.retry_base_seconds * (2 ** (attempt - 1)),
                )
                delay += random.uniform(0.0, max(0.05, delay * 0.25))
                log.warning(
                    "Sheets read rate-limited: component=%s reason=%s attempt=%d/%d",
                    component,
                    reason,
                    attempt,
                    self.retry_attempts,
                )
                if delay > 0:
                    time.sleep(delay)
        raise RuntimeError("unreachable Sheets retry state")

    def read(
        self,
        key: Hashable,
        loader: Callable[[], Any],
        *,
        policy: CachePolicy = CONFIG_DATA,
        component: str = "achievements",
        reason: str = "read",
    ) -> Any:
        key = _freeze(key)
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and policy.fresh_seconds > 0:
                if now - entry.loaded_at <= policy.fresh_seconds:
                    self._cache_hits += 1
                    return entry.value

            flight = self._inflight.get(key)
            if flight is None:
                flight = _Flight(event=threading.Event())
                self._inflight[key] = flight
                leader = True
                self._misses += 1
            else:
                leader = False
                self._coalesced += 1

        if not leader:
            flight.event.wait()
            with self._lock:
                entry = self._cache.get(key)
                if entry is not None:
                    age = time.monotonic() - entry.loaded_at
                    if policy.fresh_seconds <= 0 or age <= max(
                        policy.fresh_seconds, policy.stale_seconds
                    ):
                        return entry.value
                error = flight.error
            if error is not None:
                raise error
            return self.read(
                key,
                loader,
                policy=policy,
                component=component,
                reason=reason,
            )

        try:
            value = self._load_with_retry(
                loader,
                component=component,
                reason=reason,
            )
        except BaseException as exc:
            with self._lock:
                entry = self._cache.get(key)
                if entry is not None and policy.stale_seconds > 0:
                    age = time.monotonic() - entry.loaded_at
                    if age <= policy.stale_seconds:
                        self._stale_hits += 1
                        flight.event.set()
                        self._inflight.pop(key, None)
                        return entry.value
                flight.error = exc
                flight.event.set()
                self._inflight.pop(key, None)
            raise
        else:
            with self._lock:
                self._cache[key] = _CacheEntry(value=value, loaded_at=time.monotonic())
                flight.event.set()
                self._inflight.pop(key, None)
            return value

    def invalidate_worksheet(self, spreadsheet_id: str, worksheet_id: str) -> int:
        spreadsheet_id = str(spreadsheet_id)
        worksheet_id = str(worksheet_id)
        removed = 0
        with self._lock:
            for key in list(self._cache):
                if (
                    isinstance(key, tuple)
                    and len(key) >= 3
                    and key[0] == "values"
                    and str(key[1]) == spreadsheet_id
                    and str(key[2]) == worksheet_id
                ):
                    self._cache.pop(key, None)
                    removed += 1
            if removed:
                self._invalidations += removed
        return removed

    def invalidate_worksheet_list(self, spreadsheet_id: str) -> int:
        spreadsheet_id = str(spreadsheet_id)
        removed = 0
        with self._lock:
            for key in list(self._cache):
                if (
                    isinstance(key, tuple)
                    and len(key) >= 2
                    and key[0] == "worksheets"
                    and str(key[1]) == spreadsheet_id
                ):
                    self._cache.pop(key, None)
                    removed += 1
            if removed:
                self._invalidations += removed
        return removed

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.rate_window_seconds
            rolling = sum(1 for ts in self._physical_timestamps if ts >= cutoff)
            return {
                "read_budget_rpm": self.rpm,
                "rolling_physical_reads": rolling,
                "physical_reads": self._physical_reads,
                "cache_entries": len(self._cache),
                "inflight": len(self._inflight),
                "cache_hits": self._cache_hits,
                "stale_hits": self._stale_hits,
                "cache_misses": self._misses,
                "coalesced_joins": self._coalesced,
                "rate_limit_errors": self._rate_limits,
                "retries": self._retries,
                "invalidations": self._invalidations,
                "cooldown_seconds": max(0.0, self._cooldown_until - now),
            }


broker = SheetsReadBroker()
_ORIGINALS: dict[str, Callable[..., Any]] = {}
_INSTALL_LOCK = threading.Lock()


def _workbook_worksheets(spreadsheet: Spreadsheet) -> list[Worksheet]:
    spreadsheet_id = _sheet_id(spreadsheet)
    client_id = _client_identity(getattr(spreadsheet, "client", None))
    original = _ORIGINALS["Spreadsheet.worksheets"]
    rows = broker.read(
        ("worksheets", spreadsheet_id, client_id),
        lambda: original(spreadsheet),
        policy=HANDLE_POLICY,
        component="gspread",
        reason="worksheets",
    )
    return list(rows)


def _wrap_worksheet_write(method_name: str) -> None:
    original = getattr(Worksheet, method_name, None)
    if original is None:
        return
    _ORIGINALS[f"Worksheet.{method_name}"] = original

    def wrapped(self: Worksheet, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        spreadsheet_id, worksheet_id = _worksheet_identity(self)
        broker.invalidate_worksheet(spreadsheet_id, worksheet_id)
        return result

    wrapped.__name__ = getattr(original, "__name__", method_name)
    wrapped.__doc__ = getattr(original, "__doc__", None)
    setattr(Worksheet, method_name, wrapped)


def install_gspread_broker() -> None:
    """Install the broker once for every gspread consumer in this process."""

    with _INSTALL_LOCK:
        if getattr(Client.open_by_key, "__c1c_sheets_brokered__", False):
            return

        _ORIGINALS["Client.open_by_key"] = Client.open_by_key
        _ORIGINALS["Spreadsheet.worksheets"] = Spreadsheet.worksheets
        _ORIGINALS["Spreadsheet.worksheet"] = Spreadsheet.worksheet
        _ORIGINALS["Spreadsheet.get_worksheet"] = Spreadsheet.get_worksheet
        _ORIGINALS["Worksheet.get"] = Worksheet.get

        original_open_by_key = Client.open_by_key
        original_get = Worksheet.get

        def open_by_key(self: Client, key: str, *args: Any, **kwargs: Any) -> Spreadsheet:
            # Handles retain their HTTP client and therefore its OAuth scopes.
            # Keep handle reuse client-scoped even though value data below is
            # safely shared across clients for the same workbook/tab.
            return broker.read(
                ("workbook", str(key), _client_identity(self)),
                lambda: original_open_by_key(self, key, *args, **kwargs),
                policy=HANDLE_POLICY,
                component="gspread",
                reason="open_by_key",
            )

        def worksheets(self: Spreadsheet) -> list[Worksheet]:
            return _workbook_worksheets(self)

        def worksheet(self: Spreadsheet, title: str) -> Worksheet:
            for candidate in _workbook_worksheets(self):
                if str(getattr(candidate, "title", "")) == str(title):
                    return candidate
            raise WorksheetNotFound(title)

        def get_worksheet(self: Spreadsheet, index: int) -> Worksheet | None:
            rows = _workbook_worksheets(self)
            try:
                return rows[index]
            except IndexError:
                return None

        def get(self: Worksheet, *args: Any, **kwargs: Any) -> Any:
            spreadsheet_id, worksheet_id = _worksheet_identity(self)
            policy = _worksheet_policy(self)
            result = broker.read(
                (
                    "values",
                    spreadsheet_id,
                    worksheet_id,
                    _freeze(args),
                    _freeze(kwargs),
                ),
                lambda: original_get(self, *args, **kwargs),
                policy=policy,
                component="config" if policy is CONFIG_DATA else "help_seed",
                reason=f"values:{getattr(self, 'title', '')}",
            )
            try:
                return copy.deepcopy(result)
            except Exception:
                return result

        open_by_key.__c1c_sheets_brokered__ = True
        worksheets.__c1c_sheets_brokered__ = True
        worksheet.__c1c_sheets_brokered__ = True
        get_worksheet.__c1c_sheets_brokered__ = True
        get.__c1c_sheets_brokered__ = True

        Client.open_by_key = open_by_key
        Spreadsheet.worksheets = worksheets
        Spreadsheet.worksheet = worksheet
        Spreadsheet.get_worksheet = get_worksheet
        Worksheet.get = get

        for method_name in (
            "append_row",
            "append_rows",
            "update",
            "batch_update",
            "update_cell",
            "update_cells",
            "delete_rows",
            "insert_row",
            "insert_rows",
            "clear",
            "batch_clear",
        ):
            _wrap_worksheet_write(method_name)

        original_add_worksheet = getattr(Spreadsheet, "add_worksheet", None)
        if original_add_worksheet is not None:
            _ORIGINALS["Spreadsheet.add_worksheet"] = original_add_worksheet

            def add_worksheet(self: Spreadsheet, *args: Any, **kwargs: Any) -> Worksheet:
                result = original_add_worksheet(self, *args, **kwargs)
                broker.invalidate_worksheet_list(_sheet_id(self))
                return result

            Spreadsheet.add_worksheet = add_worksheet

        original_del_worksheet = getattr(Spreadsheet, "del_worksheet", None)
        if original_del_worksheet is not None:
            _ORIGINALS["Spreadsheet.del_worksheet"] = original_del_worksheet

            def del_worksheet(self: Spreadsheet, *args: Any, **kwargs: Any) -> Any:
                result = original_del_worksheet(self, *args, **kwargs)
                broker.invalidate_worksheet_list(_sheet_id(self))
                return result

            Spreadsheet.del_worksheet = del_worksheet

        log.info("Installed Achievements Sheets read broker: rpm=%d", broker.rpm)


def sheets_broker_snapshot() -> dict[str, Any]:
    return broker.snapshot()
