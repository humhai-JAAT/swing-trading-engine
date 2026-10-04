import threading
import time


class AccountRateLimiter:
    def __init__(self, min_interval_seconds: float):
        self._lock = threading.Lock()
        self._last_call_at = 0.0
        self._min_interval = min_interval_seconds

    def wait_for_turn(self) -> None:
        with self._lock:
            elapsed = time.time() - self._last_call_at
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call_at = time.time()

    def call(self, fn, *args, **kwargs):
        self.wait_for_turn()
        return fn(*args, **kwargs)
