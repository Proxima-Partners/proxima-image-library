"""Runner-side bounded network announcement/wait; no firewall modification."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import time

import requests

from scripts.rehearsal_runner import IsolatedTransport, require
from scripts.rehearsal_infra import HOST
from scripts.release_azure_io import STORAGE


def announce():
    with requests.Session() as session:
        session.trust_env = False
        response = session.get("https://api.ipify.org", timeout=(5, 10), allow_redirects=False)
        require(response.status_code == 200 and len(response.content) <= 64)
        address = ipaddress.ip_address(response.text.strip())
        require(address.version == 4 and address.is_global)
    report = {"run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
              "commit": os.environ["GITHUB_SHA"], "ipv4": str(address)}
    Path("runner-network.json").write_text(json.dumps(report) + "\n")
    print("Runner address artifact ready; awaiting scoped operator network rule")


def wait():
    io = IsolatedTransport()
    deadline = time.monotonic() + 600
    with requests.Session() as session:
        session.trust_env = False
        while time.monotonic() < deadline:
            code, _, _ = io.request("HEAD", STORAGE + "/ci-rehearsal?restype=container", accepted=(200, 403), timeout=10)
            response = session.get(HOST + "/health", timeout=(5, 10), allow_redirects=False)
            require(response.status_code in {200, 403, 502, 503})
            if code == 200 and response.status_code == 200:
                print("Runner network and synthetic-container read access verified")
                return
            time.sleep(5)
    raise RuntimeError("Scoped network path unavailable; no rehearsal mutations started")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("announce", "wait"))
    args = p.parse_args()
    try:
        announce() if args.action == "announce" else wait()
    except Exception:
        print("Rehearsal network check stopped; details withheld")
        raise SystemExit(1)
