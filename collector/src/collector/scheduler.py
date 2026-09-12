"""Registers one APScheduler job per fetcher, all wrapped in run_fetcher.

Every job also fires once immediately on startup (next_run_time=now) so a
fresh deployment populates within seconds instead of one full cadence. That
relies on a generous misfire_grace_time: jobs are registered during build(),
before uvicorn's ASGI startup hook actually starts the scheduler, and that
gap alone can exceed APScheduler's default 1s grace — silently dropping the
startup run on every deployment.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from collector.config import Config
from collector.fetchers.bonds import fetch_bonds
from collector.fetchers.comment import call_claude, call_claude_triage, fetch_comment
from collector.fetchers.cycle import fetch_cycle
from collector.fetchers.equity import fetch_equity
from collector.fetchers.fred import fetch_macro_history
from collector.fetchers.macro import fetch_calendar_if_due
from collector.fetchers.midnight import fetch_midnight
from collector.fetchers.morpho import fetch_morpho
from collector.fetchers.news import fetch_news
from collector.fetchers.refs import fetch_refs
from collector.fetchers.refs_history import fetch_refs_history
from collector.fetchers.zyfai import fetch_defi
from collector.http import GetBytes, GetText, PostJson
from collector.runner import run_fetcher
from collector.store import Store

log = logging.getLogger(__name__)

MACRO_HISTORY_SECONDS = 86400  # daily; not config — no reason to tune it

# The comment job reads the store, so its startup run must not race the data
# fetchers' startup runs: on a fresh volume it would summarize an empty store
# and pin that comment for a full cadence. Every other job self-heals on its
# next tick minutes later; this one is metered and twice daily, so it waits.
FIRST_RUN_DELAY = {"comment": timedelta(minutes=5)}


def comment_fetch(cfg: Config, store: Store):
    """The comment job's fetch callable, shared by the scheduler and the
    on-demand refresh endpoint so both run exactly the same thing."""
    return partial(fetch_comment, cfg, store, call_claude, call_claude_triage)


def register_jobs(
    scheduler: AsyncIOScheduler,
    cfg: Config,
    store: Store,
    get_text: GetText,
    post_json: PostJson,
    get_bytes: GetBytes,
    fred_api_key: str,
    anthropic_api_key: str,
) -> None:
    fetchers = {
        "equity": (cfg.cadences["equity"],
                   partial(fetch_equity, cfg.indexes, store, get_text)),
        "bonds": (cfg.cadences["bonds"],
                  partial(fetch_bonds, cfg.bonds, cfg.cb_rates, store, get_text,
                          fred_api_key=fred_api_key)),
        "macro": (cfg.cadences["macro"],
                  partial(fetch_calendar_if_due, cfg.calendar_url, cfg.calendar_map, store, get_text)),
        "news": (cfg.cadences["news"],
                 partial(fetch_news, cfg.feeds, store, get_text, max_items=cfg.max_news)),
        "macro_history": (MACRO_HISTORY_SECONDS,
                          partial(fetch_macro_history, cfg.series, store, fred_api_key, get_text)),
        "defi": (cfg.cadences["defi"],
                 partial(fetch_defi, cfg.defi, cfg.zyfai_base, store, get_text)),
        "midnight": (cfg.cadences["midnight"],
                     partial(fetch_midnight, cfg.defi, cfg.midnight_base, store, get_text)),
        "refs": (cfg.cadences["refs"],
                 partial(fetch_refs, cfg.refs, store, get_text, post_json)),
        "refs_history": (cfg.cadences["refs_history"],
                          partial(fetch_refs_history, cfg.refs, store, get_text)),
        "morpho": (cfg.cadences["morpho"],
                   partial(fetch_morpho, cfg.defi, store, post_json)),
        "cycle": (cfg.cadences["cycle"],
                  partial(fetch_cycle, cfg.cycle_series, store, fred_api_key, get_text, get_bytes)),
    }
    if anthropic_api_key.strip():
        fetchers["comment"] = (cfg.cadences["comment"], comment_fetch(cfg, store))
    else:
        log.info("ANTHROPIC_API_KEY not set; AI market comment disabled (optional feature)")
    now = datetime.now(timezone.utc)  # one shared timestamp: per-job datetime.now()
                                       # calls would let loop iteration order leak
                                       # microseconds into the comment job's delay
    for name, (seconds, fn) in fetchers.items():
        scheduler.add_job(
            partial(run_fetcher, name, store, fn),
            "interval",
            seconds=seconds,
            id=name,
            next_run_time=now + FIRST_RUN_DELAY.get(name, timedelta(0)),
            max_instances=1,
            coalesce=True,
            misfire_grace_time=30,  # jobs are registered before the ASGI startup hook
                                    # starts the scheduler; default 1s grace silently
                                    # drops every "fire immediately" startup run
        )
