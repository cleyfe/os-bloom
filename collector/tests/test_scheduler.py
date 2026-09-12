from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from collector.config import load_config
from collector.scheduler import register_jobs
from collector.store import Store

REPO_ROOT = Path(__file__).resolve().parents[2]


async def fake_get(url, params=None):
    raise AssertionError("no network in tests")


async def fake_post(url, json=None, headers=None):
    raise AssertionError("no network in tests")


async def fake_bytes(url, params=None, headers=None):
    raise AssertionError("no network in tests")


def test_register_jobs_creates_all_jobs_with_config_cadences(tmp_path):
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = Store(tmp_path / "t.db")
    scheduler = AsyncIOScheduler(timezone="UTC")
    register_jobs(
        scheduler, cfg, store, get_text=fake_get, post_json=fake_post,
        get_bytes=fake_bytes, fred_api_key="k"
    )
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {
        "equity", "bonds", "macro", "news", "macro_history", "defi", "midnight",
        "refs", "refs_history", "morpho", "cycle", "actuals",
    }
    assert jobs["equity"].trigger.interval.total_seconds() == 300
    assert jobs["news"].trigger.interval.total_seconds() == 600
    assert jobs["macro"].trigger.interval.total_seconds() == 3600
    assert jobs["macro_history"].trigger.interval.total_seconds() == 86400
    assert jobs["defi"].trigger.interval.total_seconds() == 900
    assert jobs["midnight"].trigger.interval.total_seconds() == 900
    assert jobs["refs"].trigger.interval.total_seconds() == 900
    assert jobs["refs_history"].trigger.interval.total_seconds() == 86400
    assert jobs["morpho"].trigger.interval.total_seconds() == 900
    assert jobs["cycle"].trigger.interval.total_seconds() == 86400
    assert jobs["actuals"].trigger.interval.total_seconds() == 600
    assert all(j.misfire_grace_time == 30 for j in jobs.values())


def test_main_builds_app(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_PATH", str(REPO_ROOT / "config.yaml"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    from collector.main import build

    app, scheduler = build()
    assert app.title == "os-bloom collector"
    assert len(scheduler.get_jobs()) == 12
