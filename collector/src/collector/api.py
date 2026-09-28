"""Read-only JSON API. App factory so tests inject their own store/config."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from collector.changes import apply_transform, to_bands
from collector.config import Config
from collector.panels import build_dashboard
from collector.store import Store

RANGE_DAYS = {"1y": 365, "5y": 5 * 365, "10y": 10 * 365}


def _fetcher_healthy(f: dict) -> bool:
    if not f["last_error_at"]:
        return True
    if not f["last_success"]:
        return False
    return f["last_success"] >= f["last_error_at"]


def create_app(store: Store, cfg: Config) -> FastAPI:
    app = FastAPI(title="os-bloom collector", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])
    series_by_id = {s.id: s for s in cfg.series}
    cycle_by_id = {s.id: s for s in cfg.cycle_series}
    index_names = {i.symbol: i.name for i in cfg.indexes}
    fx_names = {i.symbol: i.name for i in cfg.fx}
    sector_names = {r.symbol: r.name for g in cfg.sectors for r in g.rows}
    bond_names = {f"{b.country}{b.tenor}": f"{b.country} {b.tenor} yield" for b in cfg.bonds}
    cb_names = {f"{c.country}CB": c.label for c in cfg.cb_rates}
    ref_labels = {}
    for a in cfg.refs.aave:
        ref_labels[a.supply_id] = a.supply_label
        ref_labels[a.borrow_id] = a.borrow_label
    for p in cfg.refs.pendle:
        ref_labels[p.implied_id] = p.implied_label
        ref_labels[p.underlying_id] = p.underlying_label
    for f in cfg.refs.funding:
        ref_labels[f.id] = f.label

    @app.get("/api/dashboard")
    def dashboard() -> dict:
        return build_dashboard(store, cfg.indexes, now=datetime.now(timezone.utc),
                               cycle_series=cfg.cycle_series, cycle_tabs=cfg.cycle_tabs,
                               fx=cfg.fx, sectors=cfg.sectors)

    @app.get("/api/series/{series_id}")
    def series(series_id: str, range: Literal["1y", "5y", "10y", "max"] = "10y") -> dict:
        scfg = series_by_id.get(series_id)
        if scfg is not None:
            points = apply_transform(store.points(f"macro:{series_id}"), scfg.transform)
            name, unit = scfg.name, scfg.unit
        elif series_id in cycle_by_id:
            ccfg = cycle_by_id[series_id]
            points = apply_transform(store.points(f"cycle:{series_id}"), ccfg.transform)
            name, unit = ccfg.name, ccfg.unit
        elif series_id in ref_labels:
            points = store.points(f"ref:{series_id}")  # already daily percent, no transform
            name, unit = ref_labels[series_id], "%"
        elif series_id in index_names:
            points = store.points(f"idx:{series_id}")
            name, unit = index_names[series_id], "px"
        elif series_id in fx_names:
            points = store.points(f"fx:{series_id}")
            name, unit = fx_names[series_id], "px"
        elif series_id in sector_names:
            points = store.points(f"sec:{series_id}")
            name, unit = sector_names[series_id], "px"
        elif series_id in bond_names:
            points = store.points(f"yield:{series_id}")
            name, unit = bond_names[series_id], "%"
        elif series_id in cb_names:
            points = store.points(f"cb:{series_id[:-2]}")  # USCB -> cb:US
            name, unit = cb_names[series_id], "%"
        else:
            raise HTTPException(status_code=404, detail=f"unknown series: {series_id}")
        if range != "max":
            cutoff = (datetime.now(timezone.utc) - timedelta(days=RANGE_DAYS[range])).date()
            points = {d: v for d, v in points.items() if d >= cutoff}
        return {
            "id": series_id, "name": name, "unit": unit,
            "points": [[d.isoformat(), v] for d, v in sorted(points.items())],
        }

    @app.get("/api/recessions")
    def recessions() -> dict:
        bands = to_bands(store.points("cycle:usrec"))
        return {"bands": [[a.isoformat(), b.isoformat()] for a, b in bands]}

    @app.get("/healthz")
    def healthz() -> dict:
        fetchers = store.statuses()
        return {"ok": all(_fetcher_healthy(f) for f in fetchers), "fetchers": fetchers}

    return app
