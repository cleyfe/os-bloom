from datetime import date
from pathlib import Path

import pytest

from collector.fetchers.boe import fetch_spot_curve, parse_spot_curve

FIX = Path(__file__).parent / "fixtures"
XLSX = (FIX / "boe_glc_nominal_trimmed.xlsx").read_bytes()
ZIP = (FIX / "boe_latest_yield_curve_data.zip").read_bytes()


def test_parse_spot_curve_reads_requested_tenors():
    out = parse_spot_curve(XLSX, ["10", "0.5"])
    assert set(out) == {"10", "0.5"}
    assert out["10"][0] == (date(2026, 9, 17), pytest.approx(5.2074008539157886))
    assert out["0.5"][0] == (date(2026, 9, 17), pytest.approx(4.1344828345887406))
    assert len(out["10"]) == 6 and len(out["0.5"]) == 6
    # sorted by date, business days only
    assert [d for d, _ in out["10"]] == sorted(d for d, _ in out["10"])


def test_parse_spot_curve_unknown_tenor_raises():
    with pytest.raises(ValueError, match="tenor"):
        parse_spot_curve(XLSX, ["10", "99"])


async def test_fetch_spot_curve_finds_nominal_workbook_in_zip():
    async def fake_get_bytes(url, params=None, headers=None):
        assert "latest-yield-curve-data.zip" in url
        return ZIP

    out = await fetch_spot_curve(["10", "0.5"], fake_get_bytes)
    assert set(out) == {"10", "0.5"}
    assert len(out["10"]) == 6
