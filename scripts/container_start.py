"""Shellless container startup; replace PID 1 with the single Gunicorn master.

The legacy source/Oryx release still uses startup.sh. Keep its server settings
in parity here. No dependency installation, migrations or remote calls belong
in this entrypoint.
"""

import os
import sys


def gunicorn_command(port: str) -> list[str]:
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return [
        sys.executable, "-m", "gunicorn",
        f"--bind=0.0.0.0:{int(port)}",
        "--workers=1", "--timeout=300", "--keep-alive=5",
        "--access-logfile=-", "--error-logfile=-", "src.app:app",
    ]


def main() -> None:
    command = gunicorn_command(os.environ.get("PORT", "8080"))
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
