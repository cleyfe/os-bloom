"""Eurostat dissemination API, JSON-stat 2.0, keyless.

One query is one series: every dimension but time must select a single
category, which the filters in the config query guarantee. The HICP datasets
were re-based in 2026 (prc_hicp_minr replaces prc_hicp_manr) and the euro
area is EA21 since Bulgaria joined; both facts live in config.yaml, not here.
"""
from __future__ import annotations

import json
from datetime import date

from collector.http import GetText

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"


def period_to_date(period: str) -> date:
    """'2026-08' -> 2026-08-01, '2026-Q3' -> 2026-07-01, '2026' -> 2026-01-01."""
    if "-Q" in period:
        year, quarter = period.split("-Q")
        return date(int(year), 3 * (int(quarter) - 1) + 1, 1)
    parts = period.split("-")
    return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, 1)


def since_param(since: date, freq: str) -> str:
    if freq == "q":
        return f"{since.year}-Q{(since.month - 1) // 3 + 1}"
    return f"{since.year}-{since.month:02d}"


def parse_jsonstat(text: str) -> list[tuple[date, float]]:
    """A single series out of a JSON-stat response, sorted by period."""
    d = json.loads(text)
    if not isinstance(d, dict) or "value" not in d:
        raise ValueError("eurostat: no value block in response")
    non_time = [(dim, size) for dim, size in zip(d["id"], d["size"]) if dim != "time"]
    extra = [f"{dim}={size}" for dim, size in non_time if size != 1]
    if extra:
        raise ValueError("eurostat query is not a single series: " + ", ".join(extra))
    # With every other dimension collapsed to one category, the flat value
    # index is the time position.
    by_pos = {pos: period for period, pos in d["dimension"]["time"]["category"]["index"].items()}
    out = []
    for flat, value in d["value"].items():
        if value is None:
            continue
        out.append((period_to_date(by_pos[int(flat)]), float(value)))
    return sorted(out)


async def fetch_eurostat(query: str, get_text: GetText, since: date,
                         freq: str = "m") -> list[tuple[date, float]]:
    sep = "&" if "?" in query else "?"
    url = f"{BASE}{query}{sep}sinceTimePeriod={since_param(since, freq)}&format=JSON&lang=EN"
    return parse_jsonstat(await get_text(url))
