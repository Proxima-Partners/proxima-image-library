"""Fixed-target, bounded cold lifecycle evidence. No standalone deploy entrypoint."""
import re
import time

from scripts.configure_container_pilot import APP_ID
from scripts.release_azure_io import ARM, SCM, AzureIOError

API = "2024-11-01"
LOG_NAME = re.compile(r"\d{4}_\d{2}_\d{2}_[A-Za-z0-9]+_docker\.log")
CONTAINER = r"[a-z0-9]+_pp-image-library(?:_main)?"


def lifecycle_state(raw, *, container=CONTAINER):
    active, started, terminated, deleting = set(), set(), set(), None
    pull_failed = False
    for line in sorted(raw.decode("utf-8").splitlines()):
        if "Container pull image failed with reason: ImagePullFailure. Revert by terminate." in line:
            if deleting is not None or pull_failed:
                raise AzureIOError("Ambiguous failed-pull termination history")
            pull_failed = True
        if pull_failed and ("Starting container:" in line or "Deleting container:" in line):
            raise AzureIOError("Failed-pull termination overlaps named lifecycle")
        match = re.search(r"Starting container: (" + container + r")\.", line)
        if match:
            name = match[1]
            if name in started:
                raise AzureIOError("Duplicate production lifecycle identity")
            active.add(name)
            started.add(name)
        match = re.search(r"Deleting container: (" + container + r")\.", line)
        if match:
            if deleting is not None or match[1] not in active:
                raise AzureIOError("Ambiguous production termination history")
            deleting = match[1]
        if "Container is terminated." in line:
            if pull_failed and deleting is None and "Container is terminated. Total time elapsed: 0 ms." in line:
                # Azure logs this when a pull fails BEFORE creating a named
                # container. It proves no named runtime stopped: preserve both
                # active and terminated sets exactly. All other unmatched
                # termination events still fail closed.
                pull_failed = False
                continue
            if deleting is None:
                raise AzureIOError("Unmatched production termination history")
            active.remove(deleting)
            terminated.add(deleting)
            deleting = None
    if not started:
        raise AzureIOError("No named production lifecycle evidence")
    return active, terminated


class ProductionLifecycle:
    def __init__(self, transport, lease, *, slot="production", clock=time.monotonic, pause=time.sleep):
        if slot not in SCM:
            raise AzureIOError("Unapproved lifecycle slot")
        self.slot = slot
        self.resource = APP_ID + ("/slots/staging" if slot == "staging" else "")
        self.container = CONTAINER if slot == "production" else r"[a-z0-9]+_pp-image-library_[a-f0-9]{4}_main"
        self.transport, self.lease = transport, lease
        self.clock, self.pause = clock, pause

    def inventory(self, required_terminated=()):
        root = SCM[self.slot] + "/api/vfs/LogFiles/"
        entries = self.transport.json("GET", root, max_bytes=65536)
        if not isinstance(entries, list):
            raise AzureIOError("Invalid lifecycle log inventory")
        names = [entry["name"] for entry in entries
                 if isinstance(entry, dict) and LOG_NAME.fullmatch(str(entry.get("name", "")))]
        if not 1 <= len(names) <= 4 or len(set(names)) != len(names):
            raise AzureIOError("Lifecycle logs missing or exceed bounded review")
        chunks = [self.transport.request("GET", root + name, max_bytes=512 * 1024)[2]
                  for name in sorted(names)]
        active, terminated = lifecycle_state(b"\n".join(chunks), container=self.container)
        return active | (set(required_terminated) - terminated)

    def confirm_stopped(self, required_terminated=()):
        deadline = self.clock() + 90
        while self.clock() < deadline:
            self.lease.assert_held()
            app = self.transport.json("GET", ARM + self.resource + "?api-version=" + API)
            if (app.get("id", "").lower() != self.resource.lower()):
                raise AzureIOError("Unexpected lifecycle target")
            if app["properties"]["state"] == "Stopped" and not self.inventory(required_terminated):
                return
            self.pause(min(2, max(0, deadline - self.clock())))
        raise AzureIOError("Production termination unconfirmed; no mutation permitted")

    def stop(self):
        self.lease.assert_held()
        active = self.inventory()
        self.lease.checkpoint(self.slot + "_stop_requested")
        self.transport.request("POST", ARM + self.resource + "/stop?api-version=" + API,
                               accepted=(200, 204))
        self.confirm_stopped(active)
        return active

    def start(self):
        self.confirm_stopped()
        self.lease.checkpoint(self.slot + "_start_requested")
        self.transport.request("POST", ARM + self.resource + "/start?api-version=" + API,
                               accepted=(200, 204))
