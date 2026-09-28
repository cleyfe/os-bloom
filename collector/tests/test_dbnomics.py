from datetime import date
from pathlib import Path

import pytest

from collector.fetchers.dbnomics import fetch_series, parse_series

FIXTURE = (Path(__file__).parent / "fixtures" / "dbnomics_ism.json").read_text()


def test_parse_series_monthly_periods_and_null_skip():
    assert parse_series(FIXTURE) == [
        (date(2026, 5, 1), 49.5),
        (date(2026, 7, 1), 48.7),  # null June skipped
    ]


def test_parse_series_skips_na_string():
    # ONS series (e.g. UK CPI y/y) carry the string "NA" for old gaps, not null
    text = '{"series": {"docs": [{"period": ["2026-05", "2026-06", "2026-07"], "value": ["NA", 3.1, "NA"]}]}}'
    assert parse_series(text) == [(date(2026, 6, 1), 3.1)]


def test_parse_series_daily_periods():
    text = '{"series": {"docs": [{"period": ["2026-07-15"], "value": [1.5]}]}}'
    assert parse_series(text) == [(date(2026, 7, 15), 1.5)]


def test_parse_series_missing_docs_raises():
    with pytest.raises(ValueError):
        parse_series('{"series": {"docs": []}}')


async def test_fetch_series_builds_url():
    seen = {}

    async def fake_get(url, params=None):
        seen["url"] = url
        seen["params"] = params
        return FIXTURE

    pts = await fetch_series("ISM/pmi/pm", fake_get)
    assert seen["url"] == "https://api.db.nomics.world/v22/series/ISM/pmi/pm"
    assert seen["params"] == {"observations": "1"}
    assert len(pts) == 2
