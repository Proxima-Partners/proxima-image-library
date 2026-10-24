"""Exact-host Azure/SCM transport and a durable fail-closed release lease.

Uses the already authenticated Azure CLI identity (OIDC in CI). Never falls back
to publishing passwords, storage keys, browser cookies or application secrets.
No automatic retries of mutations; unknown results retain the infinite lease.
"""
from contextlib import contextmanager
import base64
from email.utils import formatdate
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import unquote, urlsplit
import uuid

import requests

from scripts.configure_container_pilot import SUB, APP_ID

ACCOUNT = "pilrelease9528"
STORAGE = f"https://{ACCOUNT}.blob.core.windows.net"
ARM = "https://management.azure.com"
SCM = {"production": "https://pp-image-library.scm.azurewebsites.net",
       "staging": "https://pp-image-library-staging.scm.azurewebsites.net"}
LEGACY_SCM = {"production": "https://pp-app-serv.scm.azurewebsites.net",
              "staging": "https://pp-app-serv-staging.scm.azurewebsites.net"}
ARM_AUDIENCE = "https://management.core.windows.net/"
STORAGE_AUDIENCE = "https://storage.azure.com/"


class AzureIOError(RuntimeError):
    pass


def scm_python_command(source):
    """Kudu parses process arguments, not POSIX shell single-quote escapes.

    Only base64 ASCII is interpolated; the one Python argument uses double
    quotes recognized by Kudu. Never pass secrets via this command builder.
    """
    if not isinstance(source, bytes) or len(source) > 256 * 1024:
        raise ValueError("Invalid bounded SCM source")
    encoded = base64.b64encode(source).decode("ascii")
    return ('python3 -c "import base64;exec(compile(base64.b64decode(\'' + encoded +
            '\'),\'<protected-scm>\',\'exec\'))"')


class AzureCLIIdentity:
    def __init__(self):
        self.cache = {}

    def token(self, audience):
        if audience not in {ARM_AUDIENCE, STORAGE_AUDIENCE}:
            raise AzureIOError("Unapproved token audience")
        cached = self.cache.get(audience)
        if cached and cached[1] > time.time() + 120:
            return cached[0]
        try:
            result = subprocess.run(["az", "account", "get-access-token", "--subscription", SUB,
                "--resource", audience, "--only-show-errors", "-o", "json"],
                capture_output=True, text=True, timeout=45)
            data = json.loads(result.stdout) if result.returncode == 0 else {}
            if data.get("subscription") != SUB or not data.get("accessToken"):
                raise ValueError()
            self.cache[audience] = (data["accessToken"], int(data["expires_on"]))
            return data["accessToken"]
        except Exception:
            raise AzureIOError("Azure identity unavailable; reauthenticate without printing credentials") from None


class AzureTransport:
    def __init__(self, identity=None, session=None):
        self.identity = identity or AzureCLIIdentity()
        self.session = session or requests.Session()
        self.session.trust_env = False  # Do not send tokens via inherited proxies.

    def request(self, method, url, *, accepted=(200,), headers=None, data=None,
                max_bytes=2 * 1024 * 1024, timeout=30):
        parsed = urlsplit(url)
        allowed = {urlsplit(x).netloc for x in [ARM, STORAGE, *SCM.values(), *LEGACY_SCM.values()]}
        decoded_path = unquote(parsed.path)
        if (parsed.scheme != "https" or parsed.netloc not in allowed or parsed.username
                or parsed.fragment or ".." in decoded_path.split("/")
                or "\\" in decoded_path or "%" in decoded_path
                or any(ord(char) < 32 for char in url)):
            raise AzureIOError("Unapproved Azure endpoint")
        audience = STORAGE_AUDIENCE if parsed.netloc == urlsplit(STORAGE).netloc else ARM_AUDIENCE
        supplied = dict(headers or {})
        if any(key.lower() == "authorization" for key in supplied):
            raise AzureIOError("Caller cannot override Azure authentication")
        supplied["Authorization"] = "Bearer " + self.identity.token(audience)
        if audience == STORAGE_AUDIENCE:
            supplied["x-ms-version"] = "2023-11-03"
            supplied["x-ms-date"] = formatdate(usegmt=True)
        try:
            with self.session.request(method, url, headers=supplied, data=data,
                    timeout=(5, timeout), allow_redirects=False, stream=True) as response:
                if response.status_code not in accepted:
                    raise AzureIOError(f"Azure request refused (HTTP {response.status_code}); body withheld")
                chunks, total = [], 0
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise AzureIOError("Azure response exceeded the bounded size")
                    chunks.append(chunk)
                return response.status_code, dict(response.headers), b"".join(chunks)
        except AzureIOError:
            raise
        except Exception:
            raise AzureIOError("Azure request outcome unknown; reconcile before another mutation") from None

    def json(self, method, url, *, body=None, **kwargs):
        headers = kwargs.pop("headers", {})
        if body is not None:
            headers = dict(headers, **{"Content-Type": "application/json"})
        _, _, raw = self.request(method, url, headers=headers,
                                data=json.dumps(body).encode() if body is not None else None, **kwargs)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            raise AzureIOError("Invalid Azure JSON response") from None


class BlobReleaseLease:
    """Infinite lease: a crashed/ambiguous run cannot silently unlock deployment.

    Blob leases fence the lock blob, NOT Azure ARM. Every cooperating writer must
    use this lock; never auto-break it. Manual lock recovery requires writers
    held and any in-flight ARM operation reconciled first.
    """
    def __init__(self, transport, recovery_path, *, blob="production.json"):
        if blob not in {"production.json", "rehearsal.json"}:
            raise ValueError("Unapproved release lock")
        self.transport, self.recovery_path = transport, Path(recovery_path)
        self.url = STORAGE + "/release-control/" + blob
        self.lease_id = str(uuid.uuid4())
        self.run_id = uuid.uuid4().hex
        self.acquired = False

    def initialize(self):
        # Separate explicit setup action; never overwrite an existing lock blob.
        status, _, _ = self.transport.request("PUT", self.url, accepted=(201, 412),
            headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, data=b'{}')
        return status == 201

    def acquire(self):
        fd = os.open(self.recovery_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"url": self.url, "lease_id": self.lease_id, "run_id": self.run_id,
                       "resource": APP_ID, "instruction": "Reconcile; never auto-break or auto-resume"}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(self.recovery_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        _, headers, _ = self.transport.request("PUT", self.url + "?comp=lease", accepted=(201,),
            headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1",
                     "x-ms-proposed-lease-id": self.lease_id})
        received = {k.lower(): v for k, v in headers.items()}.get("x-ms-lease-id")
        if received != self.lease_id:
            raise AzureIOError("Lease acknowledgement ambiguous; retain recovery record")
        self.acquired = True
        self.checkpoint("acquired")

    def assert_held(self):
        if not self.acquired:
            raise AzureIOError("Release lease not held")
        self.transport.request("PUT", self.url + "?comp=lease", accepted=(200,),
            headers={"x-ms-lease-action": "renew", "x-ms-lease-id": self.lease_id})

    def checkpoint(self, phase):
        if not re.fullmatch(r"[a-z_]{1,80}", phase):
            raise ValueError("Invalid release phase")
        self.assert_held()
        self.transport.request("PUT", self.url, accepted=(201,), headers={
            "x-ms-blob-type": "BlockBlob", "x-ms-lease-id": self.lease_id,
            "Content-Type": "application/json"}, data=json.dumps({
                "run_id": self.run_id, "resource": APP_ID, "phase": phase, "at": int(time.time()),
            }).encode())

    def release(self):
        self.checkpoint("verified_held_release_completed")
        self.transport.request("PUT", self.url + "?comp=lease", accepted=(200,),
            headers={"x-ms-lease-action": "release", "x-ms-lease-id": self.lease_id})
        self.acquired = False

    @contextmanager
    def exclusive(self, resource):
        if resource != APP_ID:
            raise AzureIOError("Lease resource mismatch")
        self.acquire()
        try:
            yield
        except BaseException:
            # Deliberately retain the infinite server-side lease. A finally
            # release would allow a second writer after an uncertain ARM call.
            raise
        else:
            self.release()
