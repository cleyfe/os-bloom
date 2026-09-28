"""DBnomics series API — keyless aggregator (ISM PMIs and future cycle series).

A series ref is "PROVIDER/dataset/series", passed straight into the v22 URL.
"""
from __future__ import annotations

import json
from datetime import date

from collector.http import GetText

BASE = "https://api.db.nomics.world/v22/series"


def _parse_period(period: str) -> date:
    parts = [int(p) for p in period.split("-")]
    if len(parts) == 2:  # monthly "YYYY-MM" -> first of month
        return date(parts[0], parts[1], 1)
    return date(parts[0], parts[1], parts[2])


def parse_series(text: str) -> list[tuple[date, float]]:
    docs = json.loads(text).get("series", {}).get("docs") or []
    if not docs:
        raise ValueError("dbnomics payload has no series docs")
    doc = docs[0]
    out = []
    for period, value in zip(doc.get("period") or [], doc.get("value") or []):
        if value is None or value == "NA":  # ONS series carry "NA" for old gaps
            continue
        out.append((_parse_period(period), float(value)))
    if not out:
        raise ValueError("dbnomics series contained no usable points")
    return out


async def fetch_series(series_ref: str, get_text: GetText) -> list[tuple[date, float]]:
    return parse_series(await get_text(f"{BASE}/{series_ref}", params={"observations": "1"}))
