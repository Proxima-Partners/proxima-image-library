"""Opt-in, bounded public checks of the fixed production custom domain.

No credentials, provider calls, redirects, retries or mutations. This is not an
authenticated catalog/SSO test, an Azure configuration check or a load test.
Run in a dedicated Linux/macOS process; stdout contains only sanitized evidence.
"""
import argparse
from datetime import datetime, timezone
import json
import os
import re
import signal
import time

import requests

ORIGIN = "https://library.liveproxima.org"
SECONDS = 30
MAX_BYTES = 32 * 1024
PROBES = (("health", "/health", 200), ("readiness", "/readyz", 200),
          ("version", "/api/version", 200),
          ("anonymous_admin_denied", "/api/maintenance/deployment-status", 401))


class Deadline(Exception):
    pass


def check(commit, build_id, *, session=None, clock=time.monotonic):
    if (not re.fullmatch(r"[a-f0-9]{40}", commit)
            or not re.fullmatch(r"[0-9]+-[1-9][0-9]*", build_id)):
        raise ValueError("Reviewed release identity required")
    report = {"schema": 1, "status": "incomplete", "at": datetime.now(timezone.utc).isoformat(),
        "origin": ORIGIN, "expected_commit": commit, "expected_build_id": build_id,
        "limits": {"seconds": SECONDS, "requests": len(PROBES), "response_bytes": MAX_BYTES, "retries": 0},
        "checks": [], "not_assessed": ["sign_in", "authenticated_catalog", "uploads", "azure_configuration",
            "registry_digest", "telemetry_window", "certificate_expiry", "representative_performance"]}
    client, started = session or requests.Session(), clock()
    client.trust_env = False  # No proxy credentials or implicit .netrc authentication.
    try:
        for name, path, status in PROBES:
            before = clock()
            if before - started >= SECONDS:
                raise Deadline()
            client.cookies.clear()
            with client.get(ORIGIN + path, headers={"Accept": "application/json", "Cache-Control": "no-cache"},
                            allow_redirects=False, stream=True,
                            timeout=min(10, SECONDS - (before - started))) as response:
                valid = response.status_code == status
                data = bytearray()
                if valid:
                    valid = response.headers.get("Content-Type", "").split(";")[0].strip().lower() == "application/json"
                if valid:
                    for chunk in response.iter_content(4096):
                        if clock() - started >= SECONDS:
                            raise Deadline()
                        if len(data) + len(chunk) > MAX_BYTES:
                            raise ValueError("Response limit")
                        data.extend(chunk)
                    body = json.loads(data)
                    valid = isinstance(body, dict)
                    if valid and name == "health":
                        valid = body.get("status") == "ok"
                    elif valid and name == "anonymous_admin_denied":
                        valid = body.get("error") == "Authentication required"
                    elif valid:
                        valid = (body.get("commit") == commit and body.get("build_id") == build_id
                                 and body.get("version") == "v2.0.0")
                        if name == "readiness":
                            valid = valid and body.get("status") == "ready" and body.get("telemetry") is True
                report["checks"].append({"name": name, "passed": valid,
                    "http_status": response.status_code, "elapsed_ms": round((clock() - before) * 1000)})
                if not valid:
                    report.update(status="failed", reason="public_contract_mismatch")
                    return report
        report["status"] = "passed"
    except Deadline:
        report.update(status="incomplete", reason="time_limit")
    except Exception:
        # Never include exception text, response bodies, headers or signed URLs.
        report.update(status="failed", reason="public_check_unavailable_or_invalid")
    finally:
        client.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--build-id", required=True)
    args = parser.parse_args(argv)
    previous = None
    try:
        if (os.getenv("IMAGE_LIBRARY_PUBLIC_CHECKS_ENABLED") != "true"
                or not hasattr(signal, "setitimer") or signal.getitimer(signal.ITIMER_REAL)[0]):
            raise ValueError("Explicit enablement and dedicated process required")
        def expired(*_):
            raise Deadline()
        previous = signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, SECONDS)
        report = check(args.commit, args.build_id)
    except Deadline:
        report = {"schema": 1, "status": "incomplete", "reason": "time_limit"}
    except Exception:
        report = {"schema": 1, "status": "failed", "reason": "configuration_required"}
    finally:
        if previous is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
    print(json.dumps(report, sort_keys=True))
    return {"passed": 0, "failed": 1, "incomplete": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
