"""Write validated immutable identity during the image build, never at startup."""

import argparse
import json
import re
from pathlib import Path


def write_build_info(commit, build_id, destination):
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise ValueError("Expected a full commit SHA")
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", build_id or ""):
        raise ValueError("Expected a nonempty safe build ID")
    Path(destination).write_text(json.dumps({"commit": commit, "build_id": build_id}) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--output", default="build_info.json")
    args = parser.parse_args()
    write_build_info(args.commit, args.build_id, args.output)
