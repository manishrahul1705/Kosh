"""Collection lock: one run at a time across threads *and* processes.

* threading.Lock — scheduler job vs. API request inside one server process.
* filelock.FileLock — server vs. CLI (`scripts/run_collection.py`) on the
  same host. Cross-platform (Linux/macOS/Windows). The OS releases the file
  lock automatically if a process dies, so a crash cannot wedge collection.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout


class CollectionAlreadyRunning(RuntimeError):
    def __init__(self) -> None:
        super().__init__("A collection run is already in progress.")


class CollectionLock:
    def __init__(self, lock_path: str | Path) -> None:
        self.lock_path = Path(lock_path)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.Lock()
        self._file_lock = FileLock(str(self.lock_path))

    @contextmanager
    def acquire(self) -> Iterator[None]:
        if not self._thread_lock.acquire(blocking=False):
            raise CollectionAlreadyRunning()
        try:
            try:
                self._file_lock.acquire(timeout=0)
            except Timeout as exc:
                raise CollectionAlreadyRunning() from exc
            try:
                yield
            finally:
                self._file_lock.release()
        finally:
            self._thread_lock.release()

    def is_locked(self) -> bool:
        if self._thread_lock.locked():
            return True
        try:
            self._file_lock.acquire(timeout=0)
        except Timeout:
            return True
        self._file_lock.release()
        return False
