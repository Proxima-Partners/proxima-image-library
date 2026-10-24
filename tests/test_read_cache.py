from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from src.read_cache import CatalogCache, catalog_cache
from src.deployment_controls import writable
from src.local_client import LocalClient


def test_concurrent_cold_reads_share_one_fetch_and_results_are_isolated():
    cache, entered, release = CatalogCache(), threading.Event(), threading.Event()
    calls = []
    def load():
        calls.append(1); entered.set()
        assert release.wait(3)
        return [{"id": "1", "fields": {"Status": "approved"}}]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(cache.get, load) for _ in range(5)]
        assert entered.wait(3)
        release.set()
        results = [f.result(timeout=3) for f in futures]
    assert len(calls) == 1
    results[0][0]["fields"]["Status"] = "changed"
    assert results[1][0]["fields"]["Status"] == "approved"
    assert cache.get(load)[0]["fields"]["Status"] == "approved"


def test_invalidation_during_refresh_discards_snapshot_before_returning():
    cache, entered, release = CatalogCache(), threading.Event(), threading.Event()
    calls = []
    def load():
        calls.append(1)
        if len(calls) == 1:
            entered.set(); assert release.wait(3)
            return [{"id": "before-write"}]
        return [{"id": "after-write"}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(cache.get, load)
        assert entered.wait(3)
        cache.invalidate(); release.set()
        assert future.result(timeout=3) == [{"id": "after-write"}]
    assert len(calls) == 2


def test_failed_refresh_does_not_return_old_data_or_poison_next_refresh():
    now = [0]
    cache = CatalogCache(ttl=1, clock=lambda: now[0])
    assert cache.get(lambda: ["old"]) == ["old"]
    now[0] = 2
    with pytest.raises(RuntimeError):
        cache.get(lambda: (_ for _ in ()).throw(RuntimeError("provider failure")))
    assert cache.stats()["refreshing"] is False
    assert cache.get(lambda: ["new"]) == ["new"]


def test_waiter_timeout_does_not_start_competing_load():
    cache, entered, release = CatalogCache(wait_seconds=0.02), threading.Event(), threading.Event()
    calls = []
    def load():
        calls.append(1); entered.set(); assert release.wait(3)
        return []
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get, load)
        assert entered.wait(3)
        with pytest.raises(TimeoutError): cache.get(load)
        release.set(); assert first.result(timeout=3) == []
    assert len(calls) == 1


@pytest.mark.parametrize("fails", [False, True])
def test_graph_write_invalidation_includes_uncertain_write_outcomes(monkeypatch, fails):
    monkeypatch.setenv("APP_READ_ONLY", "false")
    catalog_cache.invalidate()
    catalog_cache.get(lambda: ["old"])
    calls = []
    @writable
    def write():
        calls.append(1)
        if fails: raise RuntimeError("uncertain")
        return True
    if fails:
        with pytest.raises(RuntimeError): write()
    else:
        assert write() is True
    assert calls == [1]
    assert catalog_cache.stats()["live"] is False


def test_local_save_invalidates_shared_cache(tmp_path):
    client = LocalClient(tmp_path / "table.json")
    catalog_cache.get(lambda: [])
    client.create_record("fixture.webp")
    assert catalog_cache.stats()["live"] is False


def test_empty_catalog_is_cached():
    cache, calls = CatalogCache(), []
    def load(): calls.append(1); return []
    cache.get(load); cache.get(load)
    assert calls == [1] and cache.stats()["live"] is True
