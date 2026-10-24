"""Bounded lifecycle evidence for the synthetic rehearsal app only."""
import json
import re
import time

from scripts import rehearsal_infra as target
from scripts.release_azure_io import ARM, AzureIOError

LOG_ROOT = target.SCM + "/api/vfs/LogFiles/"
LOG_NAME = re.compile(r"\d{4}_\d{2}_\d{2}_[A-Za-z0-9]+_docker\.log")


def log_read_allowed(method, url):
    return method == "GET" and (url == LOG_ROOT or (
        url.startswith(LOG_ROOT) and LOG_NAME.fullmatch(url[len(LOG_ROOT):]) is not None))


def lifecycle_state(raw):
    active, started, terminated, deleting = set(), set(), set(), None
    for line in sorted(raw.decode("utf-8").splitlines()):
        match = re.search(r"Starting container: ([a-z0-9]+_pp-image-library-rehearsal_main)\.", line)
        if match:
            active.add(match[1])
            started.add(match[1])
        match = re.search(r"Deleting container: ([a-z0-9]+_pp-image-library-rehearsal_main)\.", line)
        if match:
            if deleting is not None:
                raise AzureIOError("Ambiguous rehearsal termination history")
            deleting = match[1]
        if "Container is terminated." in line:
            if deleting is None or deleting not in active:
                raise AzureIOError("Unmatched rehearsal termination history")
            active.remove(deleting)
            terminated.add(deleting)
            deleting = None
    if not started:
        raise AzureIOError("No named rehearsal lifecycle evidence")
    return active, started, terminated


def active_containers(raw):
    return lifecycle_state(raw)[0]


def inventory(io, *, required_terminated=()):
    entries = json.loads(io.request("GET", LOG_ROOT, max_bytes=65536)[2])
    names = [entry["name"] for entry in entries if LOG_NAME.fullmatch(entry.get("name", ""))]
    if not 1 <= len(names) <= 4:
        raise AzureIOError("Rehearsal lifecycle logs missing or exceed bounded review")
    chunks = [io.request("GET", LOG_ROOT + name, max_bytes=512 * 1024)[2] for name in sorted(names)]
    active, _, terminated = lifecycle_state(b"\n".join(chunks))
    if not set(required_terminated).issubset(terminated):
        # Preserve incomplete termination as active; the bounded poll continues.
        active.update(set(required_terminated) - terminated)
    return active


def confirm_stopped(io, lease, *, required_terminated=()):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        lease.assert_held()
        app = io.json("GET", ARM + target.APP_ID + "?api-version=" + target.API)
        if app["properties"]["state"] == "Stopped" and not inventory(io, required_terminated=required_terminated):
            return
        time.sleep(2)
    raise AzureIOError("Rehearsal termination not confirmed; no image mutation")


def stop(io, lease):
    known_active = inventory(io)
    lease.checkpoint("rehearsal_stop_requested")
    io.request("POST", ARM + target.APP_ID + "/stop?api-version=" + target.API, accepted=(200, 204))
    confirm_stopped(io, lease, required_terminated=known_active)
