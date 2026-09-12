import json
from datetime import date, datetime, timezone
from pathlib import Path

from collector.config import ActualRuleCfg
from collector.fetchers.actuals import compute, expected_period, fetch_actuals, format_actual, match_rule
from collector.fetchers.eurostat import BASE as EUROSTAT_BASE
from collector.fetchers.fred import BASE as FRED_BASE
from collector.store import Store

EUROSTAT_FIXTURE = (Path(__file__).parent / "fixtures" / "eurostat_hicp_total.json").read_text()
NOW = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)

CPI_MM = ActualRuleCfg(country="USD", match="CPI m/m", fred="CPIAUCSL", calc="pct_prev")
CORE_MM = ActualRuleCfg(country="USD", match="Core CPI m/m", fred="CPILFESL", calc="pct_prev")
CPI_YY = ActualRuleCfg(country="USD", match="CPI y/y", fred="CPIAUCSL", calc="pct_yoy")
NFP = ActualRuleCfg(country="USD", match="Non-Farm Employment Change", fred="PAYEMS", calc="diff_k", fmt="k",
                    exclude=["ADP"])
UNEMP = ActualRuleCfg(country="USD", match="Unemployment Rate", fred="UNRATE")
GDP = ActualRuleCfg(country="USD", match="GDP q/q", fred="A191RL1Q225SBEA", freq="q")
FED = ActualRuleCfg(country="USD", match="Federal Funds Rate", fred="DFEDTARU", freq="d", lag=1, fmt="pct2")
EU_CPI = ActualRuleCfg(country="EUR", match="CPI Flash Estimate y/y",
                       eurostat="prc_hicp_minr?geo=EA21&unit=RCH_A&coicop18=TOTAL")
EU_UNEMP = ActualRuleCfg(country="EUR", match="Unemployment Rate",
                         eurostat="une_rt_m?geo=EA21&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT", lag=2,
                         exclude=["German", "French", "Italian", "Spanish"])
RULES = [CORE_MM, CPI_MM, CPI_YY, NFP, UNEMP, GDP, FED, EU_CPI, EU_UNEMP]


def test_match_rule_is_first_match_within_country():
    assert match_rule("USD", "Core CPI m/m", RULES) is CORE_MM
    assert match_rule("USD", "CPI m/m", RULES) is CPI_MM
    assert match_rule("USD", "Advance GDP q/q", RULES) is GDP
    assert match_rule("EUR", "Unemployment Rate", RULES) is EU_UNEMP
    assert match_rule("USD", "unemployment rate", RULES) is UNEMP
    assert match_rule("EUR", "ECB Press Conference", RULES) is None
    assert match_rule("GBP", "CPI m/m", RULES) is None
    assert match_rule("USD", "Non-Farm Employment Change", RULES) is NFP
    assert match_rule("USD", "ADP Non-Farm Employment Change", RULES) is None       # look-alike, excluded
    assert match_rule("EUR", "Italian Monthly Unemployment Rate", RULES) is None    # national print, excluded
    assert match_rule("USD", "Advance GDP Price Index q/q", RULES) is None          # not "GDP q/q"


def test_expected_period():
    t = datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)
    assert expected_period(t, CPI_MM) == date(2026, 8, 1)          # August CPI, released in September
    assert expected_period(t, EU_UNEMP) == date(2026, 7, 1)        # two months back
    assert expected_period(datetime(2026, 1, 9, tzinfo=timezone.utc), CPI_MM) == date(2025, 12, 1)
    assert expected_period(datetime(2026, 2, 5, tzinfo=timezone.utc), EU_UNEMP) == date(2025, 12, 1)
    assert expected_period(datetime(2026, 7, 30, tzinfo=timezone.utc), GDP) == date(2026, 4, 1)  # Q2, advance
    assert expected_period(datetime(2026, 1, 29, tzinfo=timezone.utc), GDP) == date(2025, 10, 1)
    assert expected_period(datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc), FED) == date(2026, 9, 17)


CPI_POINTS = [(date(2025, 8, 1), 321.5), (date(2026, 6, 1), 331.0), (date(2026, 7, 1), 332.813), (date(2026, 8, 1), 334.131)]


def test_compute_each_calc():
    sep = datetime(2026, 9, 11, tzinfo=timezone.utc)
    assert round(compute(CPI_POINTS, CPI_MM, sep), 3) == 0.396
    assert round(compute(CPI_POINTS, CPI_YY, sep), 3) == round((334.131 / 321.5 - 1) * 100, 3)
    assert compute([(date(2026, 8, 1), 4.1)], UNEMP, sep) == 4.1
    assert compute([(date(2026, 7, 1), 158913.0), (date(2026, 8, 1), 159075.0)], NFP, sep) == 162.0
    assert compute([(date(2026, 1, 1), 2.1), (date(2026, 4, 1), 1.5)], GDP,
                   datetime(2026, 7, 30, tzinfo=timezone.utc)) == 1.5
    fed = [(date(2026, 9, 16), 3.75), (date(2026, 9, 17), 3.5)]
    assert compute(fed, FED, datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)) == 3.5


def test_compute_takes_the_newest_observation_in_the_window():
    """The euro-area flash can land on the last day of its own month: a release
    dated 2026-08-31 with lag 1 must print August when August is out, July
    otherwise, and never June."""
    flash_in_month = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)
    pts = [(date(2026, 6, 1), 2.0), (date(2026, 7, 1), 3.0), (date(2026, 8, 1), 3.2)]
    assert compute(pts, EU_CPI, flash_in_month) == 3.2
    assert compute(pts[:2], EU_CPI, flash_in_month) == 3.0
    assert compute(pts[:1], EU_CPI, flash_in_month) is None
    # a monthly print never reaches forward past its own month, or back past lag
    sep = datetime(2026, 9, 11, tzinfo=timezone.utc)
    assert compute([(date(2026, 7, 1), 332.0), (date(2026, 10, 1), 999.0)], UNEMP, sep) is None


def test_compute_returns_none_until_published():
    aug = datetime(2026, 9, 11, tzinfo=timezone.utc)
    assert compute(CPI_POINTS[:3], CPI_MM, aug) is None              # August not out yet
    assert compute([(date(2026, 8, 1), 334.131)], CPI_MM, aug) is None  # no previous month
    assert compute([(date(2026, 8, 1), 334.131), (date(2026, 7, 1), 332.8)], CPI_YY, aug) is None
    assert compute([], UNEMP, aug) is None
    assert compute([(date(2026, 9, 15), 3.75)], FED, datetime(2026, 9, 16, tzinfo=timezone.utc)) is None


def test_format_actual():
    assert format_actual(0.396, "pct1") == "0.4%"
    assert format_actual(-0.04, "pct1") == "0.0%"
    assert format_actual(3.5, "pct2") == "3.50%"
    assert format_actual(162.0, "k") == "162K"
    assert format_actual(-23.4, "k") == "-23K"


def seeded_store(tmp_path):
    store = Store(tmp_path / "t.db")
    rows = [
        {"name": "Core CPI m/m", "country": "USD", "time": "2026-09-11T08:30:00-04:00", "actual": None},
        {"name": "Non-Farm Employment Change", "country": "USD", "time": "2026-09-04T08:30:00-04:00", "actual": None},
        {"name": "ADP Non-Farm Employment Change", "country": "USD", "time": "2026-09-02T08:15:00-04:00", "actual": None},
        {"name": "CPI m/m", "country": "USD", "time": "2026-09-11T08:30:00-04:00", "actual": None},
        {"name": "CPI y/y", "country": "USD", "time": "2026-09-11T08:30:00-04:00", "actual": None},
        {"name": "CPI Flash Estimate y/y", "country": "EUR", "time": "2026-09-02T05:00:00-04:00", "actual": None},
        {"name": "ECB Press Conference", "country": "EUR", "time": "2026-09-10T08:45:00-04:00", "actual": None},
        {"name": "Unemployment Rate", "country": "USD", "time": "2026-09-04T08:30:00-04:00", "actual": "4.1%"},
        {"name": "Retail Sales m/m", "country": "USD", "time": "2026-09-16T08:30:00-04:00", "actual": None},
        {"name": "Bank Holiday", "country": "USD", "time": "TBD", "actual": None},
    ]
    store.put_doc("macro_calendar", {"releases": rows}, source="forexfactory")
    store.put_doc("macro_history", {"releases": rows}, source="forexfactory")
    return store


def fred_json(points, params=None):
    """A FRED reply that honours observation_start, as the real API does."""
    start = (params or {}).get("observation_start", "0000-00-00")
    return json.dumps({"observations": [{"date": d, "value": v} for d, v in points if d >= start]})


async def test_fetch_actuals_fills_due_rows_once_per_source(tmp_path):
    store = seeded_store(tmp_path)
    calendar_before = store.doc("macro_calendar").updated_at
    fetched = []

    async def fake_get(url, params=None):
        fetched.append(params["series_id"] if url == FRED_BASE else url[len(EUROSTAT_BASE):].split("?")[0])
        if url == FRED_BASE and params["series_id"] == "CPIAUCSL":
            assert params["observation_start"] == "2025-03-01"   # 18 months back: the yoy base is inside
            return fred_json([("2025-08-01", "321.5"), ("2026-07-01", "332.813"), ("2026-08-01", "334.131")], params)
        if url == FRED_BASE and params["series_id"] == "CPILFESL":
            return fred_json([("2026-07-01", "336.789"), ("2026-08-01", "337.765")], params)
        if url == FRED_BASE and params["series_id"] == "PAYEMS":
            return fred_json([("2026-07-01", "158913"), ("2026-08-01", "159075")], params)
        if url.startswith(EUROSTAT_BASE + "prc_hicp_minr?"):
            return EUROSTAT_FIXTURE
        raise AssertionError(f"unexpected fetch {url} {params}")

    label = await fetch_actuals(RULES, store, fake_get, "key", now=NOW)
    assert label == "fred+eurostat"
    assert sorted(fetched) == ["CPIAUCSL", "CPILFESL", "PAYEMS", "prc_hicp_minr"]  # one per source; m/m and y/y share
    hist = {r["name"]: r for r in store.doc("macro_history").payload["releases"]}
    assert hist["CPI m/m"]["actual"] == "0.4%" and hist["CPI m/m"]["actual_source"] == "fred"
    assert hist["CPI y/y"]["actual"] == "3.9%"
    assert hist["Core CPI m/m"]["actual"] == "0.3%"
    assert hist["Non-Farm Employment Change"]["actual"] == "162K"        # PAYEMS is already in thousands
    assert hist["Non-Farm Employment Change"]["actual_value"] == 162.0
    assert hist["ADP Non-Farm Employment Change"]["actual"] is None       # look-alike title, excluded
    assert hist["CPI Flash Estimate y/y"]["actual"] == "3.2%" and hist["CPI Flash Estimate y/y"]["actual_source"] == "eurostat"
    assert hist["CPI m/m"]["actual_value"] == 0.396 and hist["CPI m/m"]["actual_at"].endswith("Z")
    assert hist["ECB Press Conference"]["actual"] is None     # no rule
    assert hist["Unemployment Rate"]["actual"] == "4.1%"     # already filled: untouched, not refetched
    assert hist["Retail Sales m/m"]["actual"] is None         # not due yet
    assert hist["Bank Holiday"]["actual"] is None             # unparseable time
    # the calendar doc is the FF refresh clock and is never rewritten
    assert store.doc("macro_calendar").updated_at == calendar_before
    assert all(r["actual"] is None or r["name"] == "Unemployment Rate"
               for r in store.doc("macro_calendar").payload["releases"])


async def test_fetch_actuals_skips_naive_times(tmp_path):
    store = Store(tmp_path / "t.db")
    store.put_doc("macro_history", {"releases": [
        {"name": "CPI m/m", "country": "USD", "time": "2026-09-11T08:30:00", "actual": None},
    ]}, source="forexfactory")

    async def never(url, params=None):
        raise AssertionError("no fetch expected")

    await fetch_actuals(RULES, store, never, "key", now=NOW)
    assert store.doc("macro_history").payload["releases"][0]["actual"] is None


async def test_fetch_actuals_idle_when_nothing_due(tmp_path):
    store = Store(tmp_path / "t.db")
    store.put_doc("macro_history", {"releases": [
        {"name": "CPI m/m", "country": "USD", "time": "2026-09-11T08:30:00-04:00", "actual": "0.4%"},
        {"name": "CPI y/y", "country": "USD", "time": "2026-12-11T08:30:00-04:00", "actual": None},
    ]}, source="forexfactory")

    async def never(url, params=None):
        raise AssertionError("no fetch expected")

    assert await fetch_actuals(RULES, store, never, "key", now=NOW) == "fred+eurostat"
    assert await fetch_actuals(RULES, Store(tmp_path / "empty.db"), never, "key", now=NOW) == "fred+eurostat"


async def test_fetch_actuals_one_source_down_does_not_block_the_other(tmp_path):
    store = seeded_store(tmp_path)

    async def fake_get(url, params=None):
        if url == FRED_BASE:
            raise RuntimeError("fred 500")
        return EUROSTAT_FIXTURE

    await fetch_actuals(RULES, store, fake_get, "key", now=NOW)
    hist = {r["name"]: r for r in store.doc("macro_history").payload["releases"]}
    assert hist["CPI m/m"]["actual"] is None
    assert hist["CPI Flash Estimate y/y"]["actual"] == "3.2%"


async def test_fetch_actuals_leaves_unpublished_rows_for_the_next_tick(tmp_path):
    store = seeded_store(tmp_path)

    async def fake_get(url, params=None):
        if url == FRED_BASE:
            return fred_json([("2026-06-01", "331.0"), ("2026-07-01", "332.813")])  # August not out
        return EUROSTAT_FIXTURE

    await fetch_actuals(RULES, store, fake_get, "key", now=NOW)
    hist = {r["name"]: r for r in store.doc("macro_history").payload["releases"]}
    assert hist["CPI m/m"]["actual"] is None and "actual_at" not in hist["CPI m/m"]
