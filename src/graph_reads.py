"""Thread-owned HTTP pools for Graph GETs, with one bounded safe-read retry.

Writes/token POSTs never enter this transport. No redirects, ambient .netrc,
stored cookies or shared mutable Session across threads. A long Retry-After is
returned to the caller, never shortened into an early retry.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import threading
import time
from urllib.parse import urlsplit

import requests


class GraphReads:
    def __init__(self, *, factory=requests.Session, clock=time.monotonic, pause=time.sleep):
        self._factory, self._clock, self._pause = factory, clock, pause
        self._local = threading.local()

    def _session(self):
        # Drop inherited pools after fork. Production is one worker without
        # preload; PID binding also makes this safe for standalone callers.
        import os
        identity = os.getpid()
        if getattr(self._local, "pid", None) != identity:
            if hasattr(self._local, "session"):
                self._local.session.close()
            session = self._factory()
            session.trust_env = False
            session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=2, pool_maxsize=2, max_retries=0))
            self._local.session, self._local.pid = session, identity
        return self._local.session

    @staticmethod
    def _delay(header):
        if header is None:
            return 0.5
        if header.isascii() and header.isdecimal():
            return int(header) if len(header) < 10 else None
        try:
            date = parsedate_to_datetime(header)
            if date.tzinfo is None:
                return None
            return max(0, (date - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None

    def get(self, url, *, headers, timeout=15):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com"
                or not parsed.path.startswith("/v1.0/") or parsed.fragment):
            raise ValueError("Only Microsoft Graph v1.0 reads are allowed")
        if not 0 < timeout <= 30:
            raise ValueError("Unbounded Graph read timeout")
        deadline = self._clock() + timeout
        session = self._session()
        for attempt in range(2):
            session.cookies.clear()
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise requests.Timeout("Graph read deadline exceeded")
            # GET only. Deliberately no retry on exceptions or authentication
            # failures; retry only explicit throttling/transient read statuses.
            response = session.get(url, headers=dict(headers), timeout=remaining, allow_redirects=False)
            if attempt or response.status_code not in {429, 503, 504}:
                return response
            delay = self._delay(response.headers.get("Retry-After"))
            if delay is None or delay > 2 or delay + 0.25 >= deadline - self._clock():
                return response
            response.close()
            self._pause(delay)
        raise AssertionError("Unreachable")
