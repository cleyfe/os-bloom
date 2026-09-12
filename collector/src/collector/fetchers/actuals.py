"""Actual prints for released calendar rows, from free sources.

ForexFactory's free feed never carries an actual, so each release the panel
can print is matched to a FRED or Eurostat series by a rule in config.yaml
(`actuals:`), and the printed number is reproduced from that series. Which
observation is the print follows from the release time alone, so the job is
stateless and cannot mistake a stale series for a fresh one.

Writes go to macro_history only: macro_calendar's updated_at is the FF
refresh clock, and upcoming rows have no actual by definition.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from collector.config import ActualRuleCfg
from collector.fetchers.eurostat import fetch_eurostat
from collector.fetchers.fred import fetch_recent
from collector.http import GetText
from collector.store import Store

log = logging.getLogger(__name__)

FRED_LOOKBACK = timedelta(days=400)   # enough for a yoy change on monthly data
EUROSTAT_LOOKBACK_MONTHS = 18


def match_rule(country: str, title: str, rules: list[ActualRuleCfg]) -> ActualRuleCfg | None:
    for rule in rules:
        if rule.country == country and rule.match.lower() in title.lower():
            return rule
    return None


def _months_back(d: date, months: int) -> date:
    """First of the month `months` before d's month (0 = d's own month)."""
    year, month = d.year, d.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def expected_period(release_time: datetime, rule: ActualRuleCfg) -> date:
    """The observation date that is this release's print."""
    d = release_time.date()
    if rule.freq == "d":
        return d + timedelta(days=rule.lag)
    if rule.freq == "q":
        quarter_start = _months_back(d, (d.month - 1) % 3)
        return _months_back(quarter_start, 3 * rule.lag)
    return _months_back(d, rule.lag)


def compute(points: list[tuple[date, float]], rule: ActualRuleCfg,
            release_time: datetime) -> float | None:
    """The printed number, or None while the reference observation (or the
    neighbour a change needs) is not published yet."""
    if not points:
        return None
    pts = sorted(points)
    period = expected_period(release_time, rule)
    if rule.freq == "d":
        hit = next(((d, v) for d, v in pts if d >= period), None)
        return hit[1] if hit else None
    by_date = dict(pts)
    if period not in by_date:
        return None
    value = by_date[period]
    if rule.calc == "level":
        return value
    if rule.calc == "pct_yoy":
        base = by_date.get(_months_back(period, 12))
        return None if not base else (value / base - 1) * 100
    idx = [d for d, _ in pts].index(period)
    if idx == 0:
        return None
    prev = pts[idx - 1][1]
    if rule.calc == "pct_prev":
        return None if not prev else (value / prev - 1) * 100
    if rule.calc == "diff_k":
        # PAYEMS & friends are already in thousands, so the raw difference is
        # the "+162K" the calendar prints.
        return value - prev
    raise ValueError(f"unknown calc {rule.calc!r}")


def format_actual(value: float, fmt: str) -> str:
    """The calendar's own conventions: FF prints "0.4%", "3.50%", "162K", "-23K"."""
    if fmt == "pct1":
        v = round(value, 1) or 0.0  # no "-0.0%"
        return f"{v:.1f}%"
    if fmt == "pct2":
        v = round(value, 2) or 0.0
        return f"{v:.2f}%"
    if fmt == "k":
        v = round(value) or 0.0
        return f"{v:.0f}K"
    raise ValueError(f"unknown fmt {fmt!r}")


def _source(rule: ActualRuleCfg) -> tuple[str, str]:
    return ("fred", rule.fred) if rule.fred else ("eurostat", rule.eurostat)


def _due(rows: list[dict], rules: list[ActualRuleCfg], now: datetime) -> list[tuple[dict, datetime, ActualRuleCfg]]:
    out = []
    for r in rows:
        if not isinstance(r, dict) or r.get("actual"):
            continue
        try:
            t = datetime.fromisoformat(r["time"])
        except (KeyError, TypeError, ValueError):  # "TBD" rows never have a print
            continue
        if t > now:
            continue
        rule = match_rule(str(r.get("country", "")), str(r.get("name", "")), rules)
        if rule is not None:
            out.append((r, t, rule))
    return out


async def _fetch(kind: str, ident: str, freq: str, get_text: GetText, fred_api_key: str,
                 now: datetime) -> list[tuple[date, float]]:
    if kind == "fred":
        return await fetch_recent(ident, fred_api_key, get_text, since=(now - FRED_LOOKBACK).date())
    return await fetch_eurostat(ident, get_text, since=_months_back(now.date(), EUROSTAT_LOOKBACK_MONTHS),
                                freq=freq)


async def fetch_actuals(rules: list[ActualRuleCfg], store: Store, get_text: GetText,
                        fred_api_key: str, now: datetime | None = None) -> str:
    """The ten-minute job. Idle unless a released row still lacks its actual;
    then one fetch per distinct source, and every hit is written at once."""
    now = now or datetime.now(timezone.utc)
    hist = store.doc("macro_history")
    rows = list(hist.payload.get("releases", [])) if hist and isinstance(hist.payload, dict) else []
    due = _due(rows, rules, now)
    if not due:
        return "fred+eurostat"
    series: dict[tuple[str, str, str], list[tuple[date, float]] | None] = {}
    for _row, _t, rule in due:
        key = (*_source(rule), rule.freq)
        if key in series:
            continue
        try:
            series[key] = await _fetch(key[0], key[1], key[2], get_text, fred_api_key, now)
        except Exception as exc:  # noqa: BLE001 — one source down must not block the others
            log.warning("actuals: %s %s failed: %s", key[0], key[1], exc)
            series[key] = None
    hits = 0
    for row, t, rule in due:
        points = series.get((*_source(rule), rule.freq))
        if not points:
            continue
        try:
            value = compute(points, rule, t)
        except (ValueError, ZeroDivisionError) as exc:
            log.warning("actuals: %s %s: %s", row.get("country"), row.get("name"), exc)
            continue
        if value is None:
            continue
        row["actual"] = format_actual(value, rule.fmt)
        row["actual_value"] = round(value, 3)
        row["actual_source"] = _source(rule)[0]
        row["actual_at"] = now.isoformat().replace("+00:00", "Z")
        hits += 1
    if hits:
        store.put_doc("macro_history", {"releases": rows}, source=hist.source)
    return "fred+eurostat"
