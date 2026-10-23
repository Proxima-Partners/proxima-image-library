#!/usr/bin/env python3
"""Bounded, read-only readiness check for the exact deployment, not stale 200s."""

import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check_release(base_url, expected_commit, *, require_telemetry=False):
    request = Request(base_url.rstrip("/") + "/readyz", headers={"Cache-Control": "no-cache"})
    try:
        with urlopen(request, timeout=10) as response:
            data = json.load(response)
            return (response.status == 200 and isinstance(data, dict) and data.get("status") == "ready"
                    and data.get("commit") == expected_commit
                    and (not require_telemetry or data.get("telemetry") is True))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("commit")
    parser.add_argument("--attempts", type=int, default=30)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--require-telemetry", action="store_true")
    args = parser.parse_args()
    for attempt in range(1, args.attempts + 1):
        if check_release(args.url, args.commit, require_telemetry=args.require_telemetry):
            print(f"Verified {args.commit[:7]} at {args.url} after {attempt} attempt(s)")
            break
        print(f"Attempt {attempt}: expected release not ready", flush=True)
        if attempt < args.attempts:
            time.sleep(args.interval)
    else:
        raise SystemExit("Release verification failed; do not retry deployment or swap blindly")
