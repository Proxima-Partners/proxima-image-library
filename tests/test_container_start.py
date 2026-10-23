import sys

import pytest

from scripts import container_start


@pytest.mark.parametrize("port", ["", "0", "65536", "-1", "8080;sh", " 8080", "８０８０"])
def test_invalid_port_is_rejected_before_exec(port, monkeypatch):
    monkeypatch.setenv("PORT", port)
    monkeypatch.setattr(container_start.os, "execv", lambda *args: pytest.fail("exec called"))
    with pytest.raises(ValueError, match="PORT must be"):
        container_start.main()


@pytest.mark.parametrize("port,expected", [(None, "8080"), ("9000", "9000"), ("08080", "8080")])
def test_startup_replaces_process_without_shell_and_preserves_single_worker(port, expected, monkeypatch):
    if port is None:
        monkeypatch.delenv("PORT", raising=False)
    else:
        monkeypatch.setenv("PORT", port)
    calls = []
    monkeypatch.setattr(container_start.os, "execv", lambda *args: calls.append(args))
    container_start.main()
    assert calls == [(sys.executable, [
        sys.executable, "-m", "gunicorn", f"--bind=0.0.0.0:{expected}",
        "--workers=1", "--timeout=300", "--keep-alive=5",
        "--access-logfile=-", "--error-logfile=-", "src.app:app",
    ])]
