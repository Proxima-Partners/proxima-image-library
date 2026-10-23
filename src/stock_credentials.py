"""Single-worker stock credentials: environment wins; file updates are atomic.

Only this dedicated, allowlisted file is parsed when dotenv loading is disabled.
Never load arbitrary application settings or interpolate values from it. Provider
keys supplied by Azure/the parent environment are intentionally not UI-editable.
"""

from io import StringIO
import os
from pathlib import Path
import stat
import tempfile
import threading

from dotenv.parser import parse_stream

PROVIDERS = {
    "pexels": {"label": "Pexels", "keys": ["PEXELS_API_KEY"]},
    "shutterstock": {"label": "Shutterstock", "keys": ["SHUTTERSTOCK_CLIENT_ID", "SHUTTERSTOCK_CLIENT_SECRET"]},
    "unsplash": {"label": "Unsplash", "keys": ["UNSPLASH_ACCESS_KEY"]},
    "pixabay": {"label": "Pixabay", "keys": ["PIXABAY_API_KEY"]},
}
KEYS = frozenset(key for provider in PROVIDERS.values() for key in provider["keys"])
MAX_FILE_BYTES = 32768


class ManagedCredentialError(ValueError):
    pass


def validated_value(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 4096
            or any(ord(char) < 32 or ord(char) > 126 for char in value)):
        raise ValueError("Credentials must be nonempty, single-line printable values")
    return value.strip()


class StockCredentials:
    def __init__(self, path, environ=None):
        self.path = Path(path)
        self.environ = os.environ if environ is None else environ
        self._lock = threading.RLock()
        self._external = KEYS.intersection(self.environ)
        values = self._read()
        for key, value in values.items():
            if key not in self._external:
                self.environ[key] = value
        self._values = values

    def _read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return {}
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                raise ValueError("Invalid persistent credential file")
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("Invalid persistent credential file")
        values = {}
        for item in parse_stream(StringIO(raw)):
            if item.error:
                raise ValueError("Invalid persistent credential syntax")
            if item.key is None:
                continue
            if item.key not in KEYS or item.key in values:
                raise ValueError("Unexpected or duplicate persistent credential key")
            values[item.key] = validated_value(item.value)
        return values

    def editable(self, provider):
        return not self._external.intersection(PROVIDERS[provider]["keys"])

    def sources(self, provider):
        return {key: ("environment" if key in self._external else
                      "persistent" if key in self._values else "unset")
                for key in PROVIDERS[provider]["keys"]}

    def update(self, provider, updates):
        with self._lock:
            if provider not in PROVIDERS:
                raise ValueError("Unknown provider")
            if not self.editable(provider):
                raise ManagedCredentialError("Provider is environment-managed; update it in Azure configuration")
            if (not isinstance(updates, dict) or not updates
                    or not set(updates).issubset(PROVIDERS[provider]["keys"])):
                raise ValueError("Supply valid credential keys for this provider")
            # Validate the entire request before touching either disk or memory.
            clean = {key: validated_value(value) for key, value in updates.items()}
            if self._read() != self._values:
                raise RuntimeError("Credential file changed externally; restart before editing")
            values = dict(self._values, **clean)
            lines = []
            for key, value in sorted(values.items()):
                quoted = value.replace("\\", "\\\\").replace("'", "\\'")
                lines.append(f"{key}='{quoted}'\n")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".stock-credentials-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write("".join(lines))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                Path(temporary).unlink(missing_ok=True)
            self._values = values
            self.environ.update(clean)
            return sorted(clean)
