import json
from datetime import date
from pathlib import Path

import pytest

from collector.fetchers.eurostat import BASE, fetch_eurostat, parse_jsonstat, period_to_date, since_param
from collector.fetchers.fred import BASE as FRED_BASE, fetch_recent

FIXTURE = (Path(__file__).parent / "fixtures" / "eurostat_hicp_total.json").read_text()


def test_period_to_date():
    assert period_to_date("2026-08") == date(2026, 8, 1)
    assert period_to_date("2026-Q3") == date(2026, 7, 1)
    assert period_to_date("2026") == date(2026, 1, 1)


def test_since_param():
    assert since_param(date(2025, 3, 15), "m") == "2025-03"
    assert since_param(date(2025, 5, 1), "q") == "2025-Q2"


def test_parse_jsonstat_single_series_from_recorded_response():
    points = parse_jsonstat(FIXTURE)
    assert points == [(date(2026, 5, 1), 3.2), (date(2026, 6, 1), 2.8),
                      (date(2026, 7, 1), 3.0), (date(2026, 8, 1), 3.2)]


def test_parse_jsonstat_refuses_multi_series_and_errors():
    d = json.loads(FIXTURE)
    d["size"][d["id"].index("geo")] = 2
    with pytest.raises(ValueError, match="single series"):
        parse_jsonstat(json.dumps(d))
    with pytest.raises(ValueError, match="no value"):
        parse_jsonstat(json.dumps({"error": {"label": "Dataset not found"}}))


def test_parse_jsonstat_skips_null_values():
    d = json.loads(FIXTURE)
    d["value"]["3"] = None
    assert [p[0] for p in parse_jsonstat(json.dumps(d))] == [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1)]


async def test_fetch_eurostat_builds_the_url():
    seen = {}

    async def fake_get(url, params=None):
        seen["url"] = url
        return FIXTURE

    await fetch_eurostat("prc_hicp_minr?geo=EA21&unit=RCH_A&coicop18=TOTAL", fake_get,
                         since=date(2025, 3, 1), freq="m")
    assert seen["url"] == (BASE + "prc_hicp_minr?geo=EA21&unit=RCH_A&coicop18=TOTAL"
                           "&sinceTimePeriod=2025-03&format=JSON&lang=EN")


async def test_fetch_recent_passes_observation_start():
    seen = {}

    async def fake_get(url, params=None):
        seen.update(url=url, params=params)
        return json.dumps({"observations": [{"date": "2026-08-01", "value": "334.131"},
                                            {"date": "2026-07-01", "value": "."}]})

    points = await fetch_recent("CPIAUCSL", "key", fake_get, since=date(2025, 8, 1))
    assert seen["url"] == FRED_BASE
    assert seen["params"]["observation_start"] == "2025-08-01"
    assert seen["params"]["series_id"] == "CPIAUCSL"
    assert points == [(date(2026, 8, 1), 334.131)]


def test_parse_jsonstat_accepts_array_forms():
    d = json.loads(FIXTURE)
    index = d["dimension"]["time"]["category"]["index"]
    periods = sorted(index, key=index.get)
    d["dimension"]["time"]["category"]["index"] = periods
    d["value"] = [d["value"][str(i)] for i in range(len(periods))]
    assert parse_jsonstat(json.dumps(d)) == parse_jsonstat(FIXTURE)


def test_parse_jsonstat_reports_missing_metadata_as_value_error():
    with pytest.raises(ValueError, match="missing"):
        parse_jsonstat(json.dumps({"value": {"0": 1.0}}))
