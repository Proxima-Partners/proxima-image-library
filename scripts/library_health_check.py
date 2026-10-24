#!/usr/bin/env python3
"""Bounded report-only scan; explicit credentials, no dotenv or Flask import.

Run as python -m scripts.library_health_check. JSON goes to stdout. Exit 0 means
the bounded checks completed (not zero findings), 2 incomplete, 1 failed.
Linux/macOS SIGALRM also bounds slow streams and image decoding. Scheduling and
identity provisioning require separate approval; existing app secrets are unused.
"""
import argparse
import json
import os
import signal

from src.library_diagnostics import Budget, DiagnosticStop, Limits, ReadOnlyGraph, scan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-seconds", type=int, default=300)
    parser.add_argument("--max-records", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--thumbnail-sample", type=int, default=20)
    parser.add_argument("--skip-thumbnails", action="store_true")
    args = parser.parse_args(argv)
    previous, client = None, None
    try:
        if os.getenv("IMAGE_LIBRARY_DIAGNOSTICS_ENABLED") != "true":
            raise ValueError("Disabled")
        if not hasattr(signal, "setitimer") or signal.getitimer(signal.ITIMER_REAL)[0]:
            raise ValueError("Dedicated bounded process required")
        limits = Limits(seconds=args.max_seconds, records=args.max_records, pages=args.max_pages,
                        thumbnails=0 if args.skip_thumbnails else args.thumbnail_sample)
        budget = Budget(limits)
        client = ReadOnlyGraph(os.environ["IMAGE_LIBRARY_DIAGNOSTIC_TOKEN"],
            os.environ["SHAREPOINT_SITE_ID"], os.environ["SHAREPOINT_LIST_NAME"],
            os.environ["SHAREPOINT_DRIVE_ID"], budget)
        root = os.environ["SHAREPOINT_IMAGE_FOLDER"]
        def expired(*_):
            raise DiagnosticStop("time_limit")
        previous = signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, limits.seconds)
        report = scan(client, root, budget)
    except (ValueError, KeyError):
        report = {"schema": 1, "status": "failed", "reasons": ["configuration_required"]}
    except DiagnosticStop:
        report = {"schema": 1, "status": "incomplete", "reasons": ["time_limit"]}
    finally:
        if previous is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        if client is not None:
            client.session.close()
    print(json.dumps(report, sort_keys=True))
    return {"complete": 0, "incomplete": 2, "failed": 1}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
