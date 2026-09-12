"""Assemble the /api/dashboard payload (spec §5) from store contents."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from collector.changes import apply_transform, bp_move, pct_change, ref_close
from collector.config import CycleSeriesCfg, CycleTabCfg, IndexCfg
from collector.store import Store

log = logging.getLogger(__name__)

HORIZONS = ("1d", "1w", "ytd", "1y")


def _asof(ts_iso: str):
    # asof = quote ts; accepted: ~20min midnight-UTC window
    # can shift the 1d ref, self-corrects next tick
    return datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).date()


def _equity_rows(store: Store, indexes: list[IndexCfg]) -> list[dict]:
    doc = store.doc("equity_quotes")
    if doc is None:
        return []
    rows = []
    for idx in indexes:  # config order == display order
        quote = doc.payload.get(idx.symbol)
        if quote is None:
            continue
        try:
            closes = store.points(f"idx:{idx.symbol}")
            asof = _asof(quote["ts"])
            row = {"symbol": idx.symbol, "name": idx.name, "last": quote["last"],
                   "source": quote["source"], "delayed": quote["delayed"],
                   "updated_at": doc.updated_at}
            for horizon in HORIZONS:
                row[f"chg_{horizon}"] = pct_change(quote["last"], ref_close(closes, asof, horizon))
        except (KeyError, TypeError, ValueError) as exc:
            # one malformed row must degrade that row, never 500 the dashboard
            log.warning("skipping malformed equity quote for %s: %s", idx.symbol, exc)
            continue
        rows.append(row)
    return rows


def _bond_rows(store: Store) -> list[dict]:
    """Matrix rows, one per country: CB rate + 3M + 10Y, changes on the 10Y.

    Country order = doc insertion order (= bonds config order). A malformed
    entry degrades to a null cell; a country with no usable cell is dropped.
    """
    doc = store.doc("bond_quotes")
    if doc is None:
        return []
    rows: dict[str, dict] = {}
    for key, quote in doc.payload.items():
        try:
            country = quote["country"]
            row = rows.setdefault(country, {
                "country": country, "cb_pct": None, "cb_label": None,
                "y3m_pct": None, "y10_pct": None, "chg_1d_bp": None, "chg_1w_bp": None,
                "updated_at": doc.updated_at,
            })
            if key.endswith("CB"):
                row["cb_pct"] = quote["yield_pct"]
                row["cb_label"] = quote.get("label")
            elif quote["tenor"] == "3M":
                row["y3m_pct"] = quote["yield_pct"]
            elif quote["tenor"] == "10Y":
                series = store.points(f"yield:{country}10Y")
                asof = _asof(quote["ts"])
                row["y10_pct"] = quote["yield_pct"]
                row["chg_1d_bp"] = bp_move(quote["yield_pct"], ref_close(series, asof, "1d"))
                row["chg_1w_bp"] = bp_move(quote["yield_pct"], ref_close(series, asof, "1w"))
        except (KeyError, TypeError, ValueError) as exc:
            # one malformed entry must degrade its cell, never 500 the dashboard
            log.warning("skipping malformed bond quote for %s: %s", key, exc)
            continue
    return [r for r in rows.values()
            if any(r[c] is not None for c in ("cb_pct", "y3m_pct", "y10_pct"))]


def _refs_rows(store: Store, doc) -> list[dict]:
    asof = _asof(doc.updated_at)
    rows = []
    for r in doc.payload.get("rows", []):
        try:
            series = store.points(f"ref:{r['id']}")
            row = {
                "id": r["id"], "label": r["label"], "value_pct": r["value_pct"],
                "chg_1d_bp": bp_move(r["value_pct"], ref_close(series, asof, "1d")),
                "chg_1w_bp": bp_move(r["value_pct"], ref_close(series, asof, "1w")),
                "extra": r.get("extra"),
            }
        except (KeyError, TypeError, ValueError) as exc:
            # one malformed row must degrade that row, never 500 the dashboard
            log.warning("skipping malformed ref row for %s: %s", r.get("id"), exc)
            continue
        rows.append(row)
    return rows


def _refs_panel(store: Store) -> dict:
    doc = store.doc("rate_refs")
    if doc is None:
        return {"rows": [], "updated_at": None, "source": None}
    return {"rows": _refs_rows(store, doc), "updated_at": doc.updated_at, "source": doc.source}


def _macro_panel(store: Store, now: datetime) -> dict:
    """Timeline split: 'past' = last 7 days from macro_history (FF only serves
    the current week, so history is our own accumulation); 'releases' = the
    calendar's upcoming entries. Unparseable times ("TBD") stay upcoming."""
    panel = _doc_panel(store, "macro_calendar", "releases")
    upcoming = []
    for r in panel["releases"]:
        try:
            if datetime.fromisoformat(r["time"]) < now:
                continue
        except (KeyError, TypeError, ValueError):
            pass
        upcoming.append(r)
    panel["releases"] = upcoming
    hist = store.doc("macro_history")
    cutoff = now - timedelta(days=7)
    past = []
    for r in (hist.payload.get("releases", []) if hist else []):
        try:
            t = datetime.fromisoformat(r["time"])
            if cutoff <= t < now:
                past.append((t, r))
        except (KeyError, TypeError, ValueError):
            continue
    past.sort(key=lambda p: p[0])
    panel["past"] = [r for _, r in past]
    return panel


def _cycle_row(store: Store, cfg: CycleSeriesCfg, overlay: str | None) -> dict:
    """Latest transformed value + 1M/1Y diffs; a series with no data yet
    degrades to null cells, never drops the row (the tab layout is config)."""
    row = {"id": cfg.id, "name": cfg.name, "unit": cfg.unit,
           "value": None, "chg_1m": None, "chg_1y": None, "overlay": overlay}
    points = apply_transform(store.points(f"cycle:{cfg.id}"), cfg.transform)
    if not points:
        return row
    asof = max(points)
    value = points[asof]
    row["value"] = value
    for horizon in ("1m", "1y"):
        ref = ref_close(points, asof, horizon)
        row[f"chg_{horizon}"] = None if ref is None else round(value - ref, 2)
    return row


def _cycle_panel(
    store: Store, cycle_series: list[CycleSeriesCfg], cycle_tabs: list[CycleTabCfg]
) -> dict:
    by_id = {s.id: s for s in cycle_series}
    tabs = []
    for tab in cycle_tabs:
        panels = []
        for panel in tab.panels:
            rows = []
            for r in panel.rows:
                cfg = by_id.get(r.series)
                if cfg is None:  # config drift must degrade the row, not 500
                    log.warning("cycle tab %s references unknown series %s", tab.id, r.series)
                    continue
                rows.append(_cycle_row(store, cfg, r.overlay))
            panels.append({"title": panel.title, "rows": rows})
        tabs.append({"id": tab.id, "label": tab.label, "panels": panels})
    status = store.status("cycle")
    return {"tabs": tabs, "updated_at": status["last_success"] if status else None,
            "source": "cycle"}


def _comment_panel(store: Store) -> dict:
    """AI market comment; `comment` is None until the first successful run."""
    doc = store.doc("market_comment")
    if doc is None:
        return {"comment": None, "updated_at": None, "source": None}
    payload = doc.payload if isinstance(doc.payload, dict) else {}
    return {"comment": payload.get("comment"),
            "updated_at": doc.updated_at, "source": doc.source}


def _news_panel(store: Store) -> dict:
    """Headlines and links only. The stored items also carry the feed's
    summary for the AI comment; that never reaches the browser."""
    panel = _doc_panel(store, "news", "items")
    panel["items"] = [{k: v for k, v in it.items() if k != "summary"} for it in panel["items"]]
    return panel


def _doc_panel(store: Store, key: str, list_key: str) -> dict:
    doc = store.doc(key)
    if doc is None:
        return {list_key: [], "updated_at": None, "source": None}
    return {list_key: doc.payload[list_key], "updated_at": doc.updated_at, "source": doc.source}


def build_dashboard(
    store: Store,
    indexes: list[IndexCfg],
    now: datetime,
    cycle_series: list[CycleSeriesCfg] = (),
    cycle_tabs: list[CycleTabCfg] = (),
) -> dict:
    equity_doc = store.doc("equity_quotes")
    bonds_doc = store.doc("bond_quotes")
    return {
        "as_of": now.isoformat().replace("+00:00", "Z"),
        "panels": {
            "macro": _macro_panel(store, now),
            "equity": {"rows": _equity_rows(store, indexes),
                       "updated_at": equity_doc.updated_at if equity_doc else None},
            "bonds": {"rows": _bond_rows(store),
                      "updated_at": bonds_doc.updated_at if bonds_doc else None,
                      "source": bonds_doc.source if bonds_doc else None},
            "news": _news_panel(store),
            "defi": _doc_panel(store, "defi_pools", "rows"),
            "midnight": _doc_panel(store, "midnight_curve", "rows"),
            "morpho": _doc_panel(store, "morpho_markets", "rows"),
            "refs": _refs_panel(store),
            "cycle": _cycle_panel(store, list(cycle_series), list(cycle_tabs)),
            "comment": _comment_panel(store),
        },
    }
