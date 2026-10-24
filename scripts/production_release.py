"""Fail-closed production release policy; deliberately NOT wired to Azure or CI.

The adapter contract below must be implemented and rehearsed before this core
can operate production. No CLI, credentials, deployment commands, DNS changes,
state restores or deploy CLI exist here. A successful release stays drained by
default. Opt-in resume additionally requires runtime configuration approval and
an exact-build idle check. Unit tests use only an in-memory adapter.
"""

from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import time
from typing import Protocol

from scripts.configure_container_pilot import APP_ID, PLAN_ID

IMAGE_PATTERN = r"proximaimagelibrary\.azurecr\.io/image-library@sha256:[a-f0-9]{64}"


class StopRelease(RuntimeError):
    """No further mutations permitted; reconcile recorded state manually."""


class ConfirmedVerificationFailure(RuntimeError):
    """Acknowledged update failed a bounded gate; recovery still needs reconciliation."""


class Adapter(Protocol):
    """Trusted, authenticated boundary. Never implement with caller-supplied JSON.

    exclusive() holds an infinite cross-run blob lease for APP_ID. Every mutator
    also checks ownership. This serializes cooperating writers only: blob leases
    do NOT fence ARM. Never auto-break a lease after an ambiguous operation.
    observe() joins fresh ARM config, /readyz, authenticated admin status and
    auth/functional read evidence; redirects/401/timeouts are failures, not idle.
    configuration() includes settings/identity/ingress/container overrides, omitting
    only image and Azure audit timestamps; keep secret values ONLY in memory.
    freeze_state() creates a protected backup and records actual selected files,
    sizes, bytes, modes/owners after drain. A sentinel alone is NOT sufficient.
    assert_recovery_safe() independently checks configured digest, unchanged
    configuration/files, persistent drain and lease even if the app is unhealthy.
    verify() is bounded, checks fresh boot, receipt, nonroot, mount AND frozen
    file integrity, drain/zero work, auth/reads and unchanged configuration. Only
    a confirmed gate failure raises ConfirmedVerificationFailure; ambiguous I/O
    raises another exception so this core cannot blindly retry or roll back.
    """
    def exclusive(self, resource): ...
    def assert_lease(self): ...
    def observe(self, slot): ...
    def configuration(self): ...
    def drain(self): ...
    def freeze_state(self): ...
    def assert_recovery_safe(self, image, configuration, frozen): ...
    def update(self, image): ...
    def verify(self, receipt, baseline, configuration, frozen, *, seconds): ...
    def resume_verified(self, receipt, observed, configuration, frozen): ...
    def validate_resume_policy(self, resume_writes): ...
    def finalize_held(self, receipt, configuration, frozen): ...
    def prepare_resume(self, receipt, previous, configuration, frozen): ...


def validate_receipt(receipt, now=None):
    """Receipt provenance/attestation must ALSO be verified by the live adapter."""
    now = now or datetime.now(timezone.utc)
    try:
        expiry = datetime.fromisoformat(receipt["expires_at"].replace("Z", "+00:00"))
        valid = (
            receipt["status"] == "pass" and expiry.tzinfo is not None and expiry > now
            and re.fullmatch(IMAGE_PATTERN, receipt["registry_image"])
            and re.fullmatch(r"[a-f0-9]{40}", receipt["commit"])
            and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", receipt["build_id"])
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise StopRelease("A current passing immutable release receipt is required")


def check_observation(observed, slot, receipt, *, drained=None):
    expected_resource = APP_ID + ("/slots/staging" if slot == "staging" else "")
    if slot not in {"staging", "production"}:
        raise StopRelease("Unapproved slot")
    expected = {
        "resource": expected_resource, "plan": PLAN_ID, "slot": slot,
        "capacity": 1, "workers": 1, "image": receipt["registry_image"],
        "commit": receipt["commit"], "build_id": receipt["build_id"],
        "version": "v2.0.0", "uid": 65532, "gid": 65532,
        "read_only": slot == "staging", "ingest_enabled": False,
        "release_controls": True, "pilot_probe": False, "healthy": True,
        "auth_verified": True, "reads_verified": True,
    }
    if any(type(observed.get(key)) is not type(value) or observed.get(key) != value
           for key, value in expected.items()):
        raise StopRelease("Target, release or runtime safety contract differs")
    if (not re.fullmatch(r"[a-f0-9]{64}", observed.get("state_id", ""))
            or not re.fullmatch(r"[a-f0-9]{32}", observed.get("boot_id", ""))
            or type(observed.get("draining")) is not bool
            or type(observed.get("active_work")) is not int or observed["active_work"] < 0):
        raise StopRelease("Missing runtime state or work evidence")
    if drained is not None and (observed["draining"] is not drained
                                 or (drained and observed["active_work"] != 0)):
        raise StopRelease("Drain is not confirmed idle")


class Journal:
    """Exclusive, fsynced append-only phase record. No credentials or file hashes."""
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        # Existing journals are reconciliation inputs, never retry instructions.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.stream = os.fdopen(fd, "w")
        try:
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            self.stream.close()
            raise
        return self

    def phase(self, phase):
        self.stream.write(json.dumps({"phase": phase, "at": datetime.now(timezone.utc).isoformat()}) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def identity(self, candidate, prior):
        fields = ("registry_image", "commit", "build_id", "expires_at")
        self.stream.write(json.dumps({"resource": APP_ID, **{
            name: {key: receipt[key] for key in fields}
            for name, receipt in (("candidate", candidate), ("prior", prior))
        }}) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def __exit__(self, *_):
        self.stream.close()


@contextmanager
def held_lease(adapter):
    try:
        with adapter.exclusive(APP_ID):
            yield
    except Exception:
        raise StopRelease("Release/lease stopped; reconcile before further action") from None


def promote(adapter, candidate, prior, journal_path, *, drain_seconds=300,
            verify_seconds=600, resume_writes=False, monotonic=time.monotonic, pause=time.sleep):
    """Promote an already verified staging digest in place, once; leave writes held.

    Not the DNS/source-to-container cutover and not a schema/data migration tool.
    Production must already implement this contract. No automatic state restore.
    """
    for receipt in (candidate, prior):
        validate_receipt(receipt)
    if type(resume_writes) is not bool:
        raise StopRelease("Explicit boolean resume policy required")
    adapter.validate_resume_policy(resume_writes)
    if candidate["registry_image"] == prior["registry_image"]:
        raise StopRelease("Candidate must differ from the known prior release")
    if not 0 < drain_seconds <= 300 or not 0 < verify_seconds <= 600:
        raise StopRelease("Unbounded release deadline")
    with Journal(journal_path) as journal, held_lease(adapter):
        try:
            journal.identity(candidate, prior)
            adapter.assert_lease()
            check_observation(adapter.observe("staging"), "staging", candidate)
            baseline = adapter.observe("production")
            check_observation(baseline, "production", prior, drained=False)
            configuration = adapter.configuration()
            journal.phase("drain_requested")
            adapter.assert_lease()
            if adapter.drain() is not True:
                raise StopRelease("Drain acknowledgement is ambiguous")
            deadline = monotonic() + drain_seconds
            while True:
                adapter.assert_lease()
                idle = adapter.observe("production")
                check_observation(idle, "production", prior)
                if idle["state_id"] != baseline["state_id"] or idle["boot_id"] != baseline["boot_id"]:
                    raise StopRelease("State or process changed while draining")
                if not idle["draining"]:
                    raise StopRelease("Drain marker was lost")
                if idle["active_work"] == 0:
                    break
                if monotonic() >= deadline:
                    raise StopRelease("Drain deadline exceeded; leave held for reconciliation")
                pause(min(2, max(0, deadline - monotonic())))
            frozen = adapter.freeze_state()
            if frozen is None:
                raise StopRelease("Protected state checkpoint is missing")
            # Recheck staging, prior, config, actual files and lease immediately
            # before the only candidate mutation. Nothing here changes settings.
            check_observation(adapter.observe("staging"), "staging", candidate)
            adapter.assert_recovery_safe(prior["registry_image"], configuration, frozen)
            for receipt in (candidate, prior):
                validate_receipt(receipt)  # Drain time must not outlive approval.
            adapter.assert_lease()
            journal.phase("candidate_update_requested")
            if adapter.update(candidate["registry_image"]) is not True:
                raise StopRelease("Image update acknowledgement is ambiguous")
            journal.phase("candidate_update_acknowledged")
            try:
                result = adapter.verify(candidate, baseline, configuration, frozen, seconds=verify_seconds)
                check_observation(result, "production", candidate, drained=True)
                if result["state_id"] != baseline["state_id"] or result["boot_id"] == baseline["boot_id"]:
                    raise StopRelease("Mount identity or fresh boot is ambiguous; reconcile before recovery")
            except ConfirmedVerificationFailure:
                # A timeout/unknown Azure result never enters this branch. Never
                # overwrite a concurrent image/config/state change to recover.
                journal.phase("candidate_failed_reconciliation_required")
                adapter.assert_recovery_safe(candidate["registry_image"], configuration, frozen)
                validate_receipt(prior)
                adapter.assert_lease()
                journal.phase("rollback_requested_once")
                if adapter.update(prior["registry_image"]) is not True:
                    raise StopRelease("Rollback acknowledgement is ambiguous")
                restored = adapter.verify(prior, baseline, configuration, frozen, seconds=verify_seconds)
                check_observation(restored, "production", prior, drained=True)
                if restored["state_id"] != baseline["state_id"] or restored["boot_id"] == baseline["boot_id"]:
                    raise StopRelease("Rollback state/boot verification failed")
                journal.phase("rollback_cleanup_requested")
                adapter.finalize_held(prior, configuration, frozen)
                journal.phase("rollback_verified_held")
                return "rollback_verified_held"
            journal.phase("candidate_cleanup_requested")
            adapter.finalize_held(candidate, configuration, frozen)
            if resume_writes:
                adapter.assert_lease()
                validate_receipt(candidate)
                adapter.assert_recovery_safe(candidate["registry_image"], configuration, frozen)
                journal.phase("post_cleanup_resume_verification")
                result = adapter.prepare_resume(candidate, result, configuration, frozen)
                check_observation(result, "production", candidate, drained=True)
                journal.phase("verified_resume_requested_once")
                resumed = adapter.resume_verified(candidate, result, configuration, frozen)
                check_observation(resumed, "production", candidate, drained=False)
                if resumed["boot_id"] != result["boot_id"] or resumed["state_id"] != result["state_id"]:
                    raise StopRelease("Runtime changed during resume; reconcile without another mutation")
                journal.phase("candidate_verified_writable")
                return "candidate_verified_writable"
            journal.phase("candidate_verified_held")
            return "candidate_verified_held"
        except Exception:
            journal.phase("stopped_reconcile_no_retry")
            # Do not leak SDK exceptions, settings or authentication responses.
            raise StopRelease("Release stopped; reconcile journal, lease, drain, image and state before further action") from None
