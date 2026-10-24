from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts import production_release as release


def receipt(letter):
    return {"status": "pass", "registry_image": "proximaimagelibrary.azurecr.io/image-library@sha256:" + letter * 64,
            "commit": letter * 40, "build_id": letter + "-1",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}


class FakeAdapter:
    """No Azure/HTTP calls, credentials or real release mutations."""
    def __init__(self):
        self.prior, self.candidate = receipt("a"), receipt("b")
        self.current = self.prior
        self.draining = False
        self.updates = []
        self.held = False
        self.fault = None
        self.work = 0
        self.safe_checks = []
        self.overrides = {}

    @contextmanager
    def exclusive(self, resource):
        assert resource == release.APP_ID
        assert not self.held
        self.held = True
        try:
            yield
        finally:
            self.held = False

    def assert_lease(self):
        assert self.held
        if self.fault == "lease_lost" and self.draining:
            raise RuntimeError("secret SDK detail")

    def observe(self, slot):
        r = self.candidate if slot == "staging" else self.current
        result = {
            "resource": release.APP_ID + ("/slots/staging" if slot == "staging" else ""),
            "plan": release.PLAN_ID, "slot": slot, "capacity": 1, "workers": 1,
            "image": r["registry_image"], "commit": r["commit"], "build_id": r["build_id"],
            "version": "v2.0.0", "uid": 65532, "gid": 65532,
            "read_only": slot == "staging", "ingest_enabled": False,
            "release_controls": True, "pilot_probe": False, "healthy": True,
            "auth_verified": True, "reads_verified": True, "state_id": "c" * 64,
            "boot_id": ("e" if self.updates else "d") * 32,
            "draining": self.draining if slot == "production" else False, "active_work": self.work,
        }
        if slot == "production":
            result.update(self.overrides)
        return result

    def configuration(self):
        return {"secret": "not-for-journal"}

    def resume_verified(self, receipt, observed, configuration, frozen):
        self.assert_lease()
        assert self.draining and self.work == 0
        self.draining = False
        if self.fault == "resume_ambiguous":
            raise TimeoutError("secret resume outcome")
        return self.observe("production")

    def drain(self):
        self.draining = True
        if self.fault == "drain_ambiguous":
            raise TimeoutError("secret transport response")
        return True

    def freeze_state(self):
        assert self.draining and self.work == 0
        if self.fault == "backup_missing":
            return None
        return object()

    def assert_recovery_safe(self, image, configuration, frozen):
        self.assert_lease()
        assert image == self.current["registry_image"]
        assert configuration == self.configuration()
        assert frozen is not None and self.draining
        self.safe_checks.append(image)
        if self.fault in {"concurrent_config", "concurrent_image", "changed_files"} and self.updates:
            raise RuntimeError("Concurrent protected-state change")

    def update(self, image):
        self.assert_lease()
        assert self.draining
        self.updates.append(image)
        self.current = self.candidate if image == self.candidate["registry_image"] else self.prior
        if self.fault == "update_ambiguous":
            raise TimeoutError("secret transport response")
        if self.fault == "rollback_ambiguous" and len(self.updates) == 2:
            return None
        return True

    def verify(self, receipt, baseline, configuration, frozen, *, seconds):
        assert 0 < seconds <= 600
        if self.fault == "verify_ambiguous":
            raise TimeoutError("unknown verification outcome")
        if self.fault and self.fault not in {"state_changed", "same_boot", "resume_ambiguous"} and len(self.updates) == 1:
            raise release.ConfirmedVerificationFailure("bounded confirmed failure")
        if self.fault == "rollback_failed" and len(self.updates) == 2:
            raise release.ConfirmedVerificationFailure("prior unhealthy")
        result = self.observe("production")
        if len(self.updates) == 1:
            if self.fault == "state_changed":
                result["state_id"] = "f" * 64
            if self.fault == "same_boot":
                result["boot_id"] = baseline["boot_id"]
        return result


def run(adapter, tmp_path, **kwargs):
    return release.promote(adapter, adapter.candidate, adapter.prior, tmp_path / "release.jsonl", **kwargs)


def test_verified_promotion_leaves_drain_and_releases_lease(tmp_path):
    adapter = FakeAdapter()
    assert run(adapter, tmp_path) == "candidate_verified_held"
    assert adapter.updates == [adapter.candidate["registry_image"]]
    assert adapter.draining and not adapter.held
    text = (tmp_path / "release.jsonl").read_text()
    assert "not-for-journal" not in text and "secret" not in text
    assert json.loads(text.splitlines()[0])["candidate"]["commit"] == "b" * 40
    assert "candidate_verified_held" in text
    with pytest.raises(FileExistsError):
        run(adapter, tmp_path)
    assert len(adapter.updates) == 1


def test_explicit_resume_only_after_verified_promotion(tmp_path):
    adapter = FakeAdapter()
    assert run(adapter, tmp_path, resume_writes=True) == "candidate_verified_writable"
    assert not adapter.draining and adapter.updates == [adapter.candidate["registry_image"]]
    assert "verified_resume_requested_once" in (tmp_path / "release.jsonl").read_text()


def test_ambiguous_resume_never_replays_or_rolls_back_after_possible_writes(tmp_path):
    adapter = FakeAdapter(); adapter.fault = "resume_ambiguous"
    with pytest.raises(release.StopRelease): run(adapter, tmp_path, resume_writes=True)
    assert len(adapter.updates) == 1 and adapter.draining is False


def test_rollback_does_not_implicitly_resume_writes(tmp_path):
    adapter = FakeAdapter(); adapter.fault = "confirmed_failure"
    assert run(adapter, tmp_path, resume_writes=True) == "rollback_verified_held"
    assert adapter.draining and len(adapter.updates) == 2


@pytest.mark.parametrize("key,value", [("resource", "PP-App-Serv"), ("plan", "shared-S1"),
    ("workers", 2), ("capacity", 2), ("read_only", True), ("ingest_enabled", True),
    ("auth_verified", False), ("reads_verified", False), ("pilot_probe", True),
    ("release_controls", False), ("uid", 0), ("state_id", ""), ("active_work", False)])
def test_unsafe_target_rejected_before_drain_or_update(tmp_path, key, value):
    adapter = FakeAdapter()
    adapter.overrides[key] = value
    with pytest.raises(release.StopRelease):
        run(adapter, tmp_path)
    assert not adapter.draining and not adapter.updates and not adapter.held


@pytest.mark.parametrize("key,value", [("registry_image", "proximaimagelibrary.azurecr.io/image-library:latest"),
    ("registry_image", "other.azurecr.io/image-library@sha256:" + "a" * 64),
    ("status", "fail"), ("commit", "invalid"), ("build_id", "secret?query"),
    ("expires_at", "2020-01-01T00:00:00Z"), ("expires_at", "2099-01-01T00:00:00")])
def test_invalid_receipts_never_start(tmp_path, key, value):
    adapter = FakeAdapter()
    adapter.candidate[key] = value
    with pytest.raises(release.StopRelease):
        run(adapter, tmp_path)
    assert not adapter.draining and not adapter.updates
    assert not (tmp_path / "release.jsonl").exists()


@pytest.mark.parametrize("fault,updates", [("drain_ambiguous", 0), ("lease_lost", 0),
    ("backup_missing", 0), ("update_ambiguous", 1), ("verify_ambiguous", 1),
    ("concurrent_config", 1), ("concurrent_image", 1), ("changed_files", 1),
    ("rollback_ambiguous", 2), ("rollback_failed", 2), ("state_changed", 1), ("same_boot", 1)])
def test_ambiguous_or_changed_state_stops_without_blind_retry(tmp_path, fault, updates):
    adapter = FakeAdapter()
    adapter.fault = fault
    with pytest.raises(release.StopRelease) as exc:
        run(adapter, tmp_path)
    assert "secret" not in str(exc.value)
    assert len(adapter.updates) == updates
    assert adapter.draining and not adapter.held
    assert "stopped_reconcile_no_retry" in (tmp_path / "release.jsonl").read_text()


@pytest.mark.parametrize("fault", ["confirmed_failure"])
def test_confirmed_failure_reconciles_and_rolls_back_exactly_once(tmp_path, fault):
    adapter = FakeAdapter()
    adapter.fault = fault
    assert run(adapter, tmp_path) == "rollback_verified_held"
    assert adapter.updates == [adapter.candidate["registry_image"], adapter.prior["registry_image"]]
    assert adapter.safe_checks == [adapter.prior["registry_image"], adapter.candidate["registry_image"]]
    assert adapter.draining


def test_busy_drain_times_out_without_any_image_update(tmp_path):
    adapter = FakeAdapter()
    adapter.work = 1
    clock = [0]
    def advance(seconds):
        clock[0] += seconds
    with pytest.raises(release.StopRelease):
        run(adapter, tmp_path, drain_seconds=3, monotonic=lambda: clock[0], pause=advance)
    assert clock[0] == 3 and not adapter.updates and adapter.draining


def test_prior_and_staging_receipts_must_match_observed_release(tmp_path):
    adapter = FakeAdapter()
    adapter.current = deepcopy(adapter.prior)
    adapter.current["build_id"] = "unexpected-build"
    with pytest.raises(release.StopRelease):
        run(adapter, tmp_path)
    assert not adapter.updates and not adapter.draining


def test_receipt_expiring_during_drain_prevents_update(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    real_freeze = adapter.freeze_state
    def expire():
        adapter.candidate["expires_at"] = "2020-01-01T00:00:00Z"
        return real_freeze()
    monkeypatch.setattr(adapter, "freeze_state", expire)
    with pytest.raises(release.StopRelease):
        run(adapter, tmp_path)
    assert not adapter.updates and adapter.draining
