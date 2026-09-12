"""ForexFactory weekly calendar -> 'macro_calendar' doc + 'macro_history' doc.

Filter: USD/EUR + High impact. The scheduler job runs hourly; should_refresh
implements the spec cadence (6h baseline, hourly on days with releases).

FF only publishes the current week (lastweek/nextweek endpoints 404), so the
panel's past-7-days section is fed by 'macro_history': every real fetch
upserts its releases keyed (country, name, time) — re-fetches refresh actuals
and revisions — retained 30 days.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from collector.config import CalendarMapEntry
from collector.http import GetText
from collector.store import Store

COUNTRIES = {"USD", "EUR"}
BASE_SECONDS = 6 * 3600
RELEASE_DAY_SECONDS = 55 * 60
HISTORY_DAYS = 30
ACTUAL_FIELDS = ("actual", "actual_value", "actual_source", "actual_at")  # written by fetchers.actuals


def _map_series(country: str, title: str, cal_map: list[CalendarMapEntry]) -> str | None:
    for entry in cal_map:
        if entry.country == country and entry.match.lower() in title.lower():
            return entry.series
    return None


def _merge_history(existing: list[dict], releases: list[dict], now: datetime) -> list[dict]:
    """Upsert releases into history keyed (country, name, time); prune to 30d."""
    by_key = {(r.get("country"), r.get("name"), r.get("time")): r for r in existing}
    for r in releases:
        key = (r["country"], r["name"], r["time"])
        old = by_key.get(key)
        # FF never carries an actual; keep the one the actuals job wrote.
        if old and not r.get("actual") and old.get("actual"):
            r = {**r, **{k: old[k] for k in ACTUAL_FIELDS if k in old}}
        by_key[key] = r
    cutoff = now - timedelta(days=HISTORY_DAYS)
    kept = []
    for r in by_key.values():
        try:
            t = datetime.fromisoformat(r["time"])
            if t >= cutoff:
                kept.append((t, r))
        except (KeyError, TypeError, ValueError):  # "TBD"-time events never enter history
            continue
    kept.sort(key=lambda p: p[0])
    return [r for _, r in kept]


async def fetch_calendar(
    url: str,
    cal_map: list[CalendarMapEntry],
    store: Store,
    get_text: GetText,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    events = json.loads(await get_text(url))
    releases = []
    for ev in events:
        try:
            if ev["country"] not in COUNTRIES or ev["impact"] != "High":
                continue
            releases.append({
                "name": ev["title"],
                "country": ev["country"],
                "time": ev["date"],
                "impact": ev["impact"],
                "previous": ev.get("previous") or None,
                "consensus": ev.get("forecast") or None,
                "actual": ev.get("actual") or None,
                "series_id": _map_series(ev["country"], ev["title"], cal_map),
            })
        except (KeyError, TypeError, AttributeError):  # one malformed event must not blank the calendar
            continue
    store.put_doc("macro_calendar", {"releases": releases}, source="forexfactory")
    hist = store.doc("macro_history")
    existing = hist.payload.get("releases", []) if hist else []
    store.put_doc("macro_history", {"releases": _merge_history(existing, releases, now)},
                  source="forexfactory")
    return "forexfactory"


def has_release_on(releases: list[dict], day: date) -> bool:
    for r in releases:
        try:
            if datetime.fromisoformat(r["time"]).date() == day:
                return True
        except (KeyError, TypeError, ValueError):  # e.g. FF emits "TBD"
            continue
    return False


def should_refresh(last_success_iso: str | None, release_today: bool, now: datetime) -> bool:
    if last_success_iso is None:
        return True
    last = datetime.fromisoformat(last_success_iso.replace("Z", "+00:00"))
    age = (now - last).total_seconds()
    if age > BASE_SECONDS:
        return True
    return release_today and age > RELEASE_DAY_SECONDS


async def fetch_calendar_if_due(
    url: str,
    cal_map: list[CalendarMapEntry],
    store: Store,
    get_text: GetText,
    now: datetime | None = None,
) -> str:
    """The hourly scheduler job. Returns the active source label either way.

    The refresh clock is the doc's own updated_at (it moves only on a real
    fetch) — NOT fetcher_status.last_success, which run_fetcher re-stamps on
    every tick including skips.
    """
    now = now or datetime.now(timezone.utc)
    doc = store.doc("macro_calendar")
    last_fetch = doc.updated_at if doc else None
    releases = doc.payload.get("releases", []) if doc else []
    release_today = has_release_on(releases, now.date())
    # A fresh calendar doc is not proof there's nothing to do: a deployment
    # that predates (or lost) macro_history would strand the past section
    # empty until the 6h cadence expires. Missing history forces a fetch.
    history_missing = store.doc("macro_history") is None
    if history_missing or should_refresh(last_fetch, release_today, now):
        return await fetch_calendar(url, cal_map, store, get_text, now=now)
    return "forexfactory"
