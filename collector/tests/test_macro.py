from datetime import date, datetime, timezone
from pathlib import Path

from collector.config import CalendarMapEntry
from collector.fetchers.macro import fetch_calendar, has_release_on, should_refresh
from collector.store import Store

FIXTURE = (Path(__file__).parent / "fixtures" / "ff_calendar.json").read_text()

CAL_MAP = [
    CalendarMapEntry(country="USD", match="Core CPI", series="us-core-cpi-yoy"),
    CalendarMapEntry(country="USD", match="CPI", series="us-cpi-yoy"),
    CalendarMapEntry(country="EUR", match="CPI", series="ez-hicp-yoy"),
]


async def fake_get(url, params=None):
    return FIXTURE


async def test_filters_to_high_impact_us_eu_and_maps_series(tmp_path):
    store = Store(tmp_path / "t.db")
    label = await fetch_calendar("http://x", CAL_MAP, store, fake_get)
    assert label == "forexfactory"
    releases = store.doc("macro_calendar").payload["releases"]
    titles = [r["name"] for r in releases]
    assert "French Trade Balance" not in titles  # Low impact dropped
    assert "BOJ Policy Rate" not in titles       # JPY dropped
    core = next(r for r in releases if r["name"] == "Core CPI m/m")
    assert core["series_id"] == "us-core-cpi-yoy"  # first-match-wins ordering
    ez = next(r for r in releases if "Flash" in r["name"])
    assert ez["series_id"] == "ez-hicp-yoy"
    assert ez["actual"] == "1.8%"
    assert core["actual"] is None
    assert core["consensus"] == "0.3%" and core["previous"] == "0.2%"


async def test_history_accumulates_and_updates_without_duplicates(tmp_path):
    import json as _json

    store = Store(tmp_path / "t.db")
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    await fetch_calendar("http://x", CAL_MAP, store, fake_get, now=now)
    hist = store.doc("macro_history").payload["releases"]
    assert len(hist) == 3  # the same High USD/EUR events as the calendar

    events = _json.loads(FIXTURE)
    for ev in events:
        if ev["title"] == "Core CPI m/m":
            ev["actual"] = "0.4%"  # released since the last fetch

    async def get_updated(url, params=None):
        return _json.dumps(events)

    await fetch_calendar("http://x", CAL_MAP, store, get_updated, now=now)
    hist = store.doc("macro_history").payload["releases"]
    assert len(hist) == 3  # upserted, not appended
    core = next(r for r in hist if r["name"] == "Core CPI m/m")
    assert core["actual"] == "0.4%"
    assert [r["time"] for r in hist] == sorted(r["time"] for r in hist)


async def test_history_prunes_entries_older_than_30_days(tmp_path):
    store = Store(tmp_path / "t.db")
    store.put_doc("macro_history", {"releases": [
        {"name": "Ancient NFP", "country": "USD", "time": "2026-05-01T08:30:00-04:00"},
        {"name": "Recent GDP", "country": "USD", "time": "2026-06-25T08:30:00-04:00"},
        {"name": "No time", "country": "USD", "time": "TBD"},
    ]}, source="forexfactory")
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    await fetch_calendar("http://x", CAL_MAP, store, fake_get, now=now)
    names = [r["name"] for r in store.doc("macro_history").payload["releases"]]
    assert "Ancient NFP" not in names       # > 30 days old
    assert "No time" not in names           # unparseable time never enters history
    assert "Recent GDP" in names            # kept alongside the 3 fresh events
    assert len(names) == 4


async def test_fresh_calendar_but_missing_history_still_fetches(tmp_path):
    """Rollout/self-heal: a pre-history deployment leaves a fresh macro_calendar
    with no macro_history doc; the skip logic must not strand the panel empty
    until the 6h cadence expires."""
    from collector.fetchers.macro import fetch_calendar_if_due

    store = Store(tmp_path / "t.db")
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    store.put_doc("macro_calendar", {"releases": []}, source="forexfactory")  # fresh, just stamped

    calls = {"n": 0}

    async def counting_get(url, params=None):
        calls["n"] += 1
        return FIXTURE

    await fetch_calendar_if_due("http://x", CAL_MAP, store, counting_get, now=now)
    assert calls["n"] == 1                          # fetched despite fresh calendar
    assert store.doc("macro_history") is not None   # history now seeded
    # with history present and calendar fresh, the next tick skips again
    await fetch_calendar_if_due("http://x", CAL_MAP, store, counting_get, now=now)
    assert calls["n"] == 1


def test_has_release_on():
    releases = [{"time": "2026-07-10T12:30:00-04:00"}]
    assert has_release_on(releases, date(2026, 7, 10)) is True
    assert has_release_on(releases, date(2026, 7, 11)) is False


def test_should_refresh():
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    assert should_refresh(None, False, now) is True                       # never fetched
    fresh = "2026-07-09T11:30:00Z"
    stale = "2026-07-09T05:00:00Z"
    assert should_refresh(fresh, False, now) is False                     # 30min old, quiet day
    assert should_refresh(stale, False, now) is True                      # >6h old
    assert should_refresh(fresh, True, now) is False                      # 30min old, release day
    hourish = "2026-07-09T10:55:00Z"
    assert should_refresh(hourish, True, now) is True                     # >55min old, release day


async def test_malformed_event_skipped_not_fatal(tmp_path):
    import json as _json

    store = Store(tmp_path / "t.db")
    events = _json.loads(FIXTURE)
    events.insert(0, {"title": "Broken event", "country": "USD"})  # no impact key

    async def get_with_bad_event(url, params=None):
        return _json.dumps(events)

    await fetch_calendar("http://x", CAL_MAP, store, get_with_bad_event)
    releases = store.doc("macro_calendar").payload["releases"]
    assert len(releases) == 3  # the 3 good High USD/EUR events survive


def test_has_release_on_tolerates_bad_time_strings():
    releases = [{"time": "TBD"}, {"time": "2026-07-10T12:30:00-04:00"}, {}]
    assert has_release_on(releases, date(2026, 7, 10)) is True
    assert has_release_on([{"time": "TBD"}], date(2026, 7, 10)) is False


async def test_refresh_clock_survives_hourly_success_stamps(tmp_path):
    """Regression: composed run_fetcher x fetch_calendar_if_due across ticks."""
    import json as _json
    from datetime import timedelta
    from functools import partial

    from collector.fetchers.macro import fetch_calendar_if_due
    from collector.runner import run_fetcher

    store = Store(tmp_path / "t.db")
    calls = {"n": 0}

    # Quiet-day feed: FIXTURE with all release times pushed far into the past,
    # so release_today is False no matter what real date the test runs on
    # (the raw FIXTURE has releases on 2026-07-09/10, which would flip the
    # cadence to hourly whenever the wall clock lands on those dates).
    events = _json.loads(FIXTURE)
    for ev in events:
        ev["date"] = "2020-01-01T09:00:00-04:00"
    quiet_feed = _json.dumps(events)

    async def counting_get(url, params=None):
        calls["n"] += 1
        return quiet_feed

    base = datetime.now(timezone.utc)

    async def tick(at):
        await run_fetcher(
            "macro", store,
            partial(fetch_calendar_if_due, "http://x", CAL_MAP, store, counting_get, now=at),
        )

    await tick(base)                              # first run fetches
    assert calls["n"] == 1
    for h in (1, 2, 3, 4, 5):                     # quiet-day hourly ticks: no refetch
        await tick(base + timedelta(hours=h))
    assert calls["n"] == 1
    await tick(base + timedelta(hours=6, minutes=5))   # past 6h baseline: refetch
    assert calls["n"] == 2


async def test_refetch_keeps_actuals_written_by_the_actuals_job(tmp_path):
    """FF never carries an actual, so its rows arrive with actual=None on every
    refetch; the merge must not erase what the actuals job filled in."""
    store = Store(tmp_path / "t.db")
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    await fetch_calendar("http://x", CAL_MAP, store, fake_get, now=now)
    hist = store.doc("macro_history").payload["releases"]
    core = next(r for r in hist if r["name"] == "Core CPI m/m")
    core.update(actual="0.4%", actual_value=0.396, actual_source="fred", actual_at="2026-07-10T13:05:00Z")
    store.put_doc("macro_history", {"releases": hist}, source="forexfactory")

    await fetch_calendar("http://x", CAL_MAP, store, fake_get, now=now)   # FF row still has actual=None
    core = next(r for r in store.doc("macro_history").payload["releases"] if r["name"] == "Core CPI m/m")
    assert core["actual"] == "0.4%" and core["actual_source"] == "fred" and core["actual_at"]
    assert core["consensus"] == "0.3%"   # the FF fields still refresh
