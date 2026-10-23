"""Single-process catalog cache with one refresh and generation-safe invalidation.

No stale-on-error fallback and no shared mutable results. This is not distributed
state and does not authorize additional application processes or instances.
"""
from copy import deepcopy
import threading
import time


class CatalogCache:
    def __init__(self, ttl=300, wait_seconds=45, clock=time.monotonic):
        self.ttl, self.wait_seconds, self.clock = ttl, wait_seconds, clock
        self._condition = threading.Condition()
        self._value, self._expires, self._generation, self._loading = None, 0, 0, False

    def invalidate(self):
        with self._condition:
            self._generation += 1
            self._value, self._expires = None, 0
            self._condition.notify_all()

    def stats(self):
        with self._condition:
            live = self._value is not None and self.clock() < self._expires
            return {"live": live, "size": len(self._value) if live else 0, "refreshing": self._loading}

    def get(self, load):
        deadline = self.clock() + self.wait_seconds
        while True:
            with self._condition:
                if self._value is not None and self.clock() < self._expires:
                    return deepcopy(self._value)
                left = deadline - self.clock()
                if left <= 0:
                    raise TimeoutError("Catalog refresh deadline exceeded")
                if self._loading:
                    self._condition.wait(timeout=left)
                    continue
                generation, self._loading = self._generation, True
            try:
                # Loader owns its network deadlines; waiters never start a
                # second load just because their own waiting deadline expires.
                value = load()
                if not isinstance(value, list):
                    raise ValueError("Invalid catalog response")
                with self._condition:
                    if generation == self._generation:
                        self._value = deepcopy(value)
                        self._expires = self.clock() + self.ttl
                        return deepcopy(value)
                    # A write invalidated the in-flight snapshot. Discard it;
                    # neither this caller nor waiting callers may publish it.
            finally:
                with self._condition:
                    self._loading = False
                    self._condition.notify_all()


catalog_cache = CatalogCache()
