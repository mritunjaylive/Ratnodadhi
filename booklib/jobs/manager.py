"""
manager.py – Central background JobManager ensuring concurrency safety.

Lanes:
- heavy:       at most 1 concurrent job (scans, lookups, hashing, sync)
- io:          at most 2 concurrent jobs (downloads, uploads, thumbnails)
- convert:     at most 1 concurrent Calibre process (configurable)
- maintenance: runs alone; blocks other heavy jobs while active
               (rename apply, restore, compact, import)
"""
from __future__ import annotations

import logging
from typing import Any
from collections import deque

from PySide6.QtCore import QObject, QThread, QTimer, Signal

logger = logging.getLogger(__name__)


class BaseJob(QThread):
    """Abstract base class for all background jobs."""

    progress = Signal(int, int, str)   # done, total, message
    finished = Signal(object)          # summary dict/object
    error    = Signal(str, str)        # context, error message
    data_changed = Signal()            # emitted when DB changed

    def __init__(self, name: str, lane: str = "heavy", parent=None) -> None:
        super().__init__(parent)
        self.name = name
        self.lane = lane               # 'heavy' | 'io' | 'convert' | 'maintenance'
        self._is_cancelled = False
        self._is_paused = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def pause(self) -> None:
        self._is_paused = True

    def resume(self) -> None:
        self._is_paused = False

    def is_paused(self) -> bool:
        return self._is_paused


class JobManager(QObject):
    """
    Coordinates execution of background jobs across four lanes:
    - heavy lane:       at most 1 concurrent job (scans, lookups, hashing, sync)
    - io lane:          at most 2 concurrent jobs (downloads, uploads, thumbnails)
    - convert lane:     at most 1 concurrent Calibre process (configurable)
    - maintenance lane: runs alone; blocks heavy lane while active
                        (rename apply, restore, compact, import)
    """

    job_started  = Signal(str)                    # job_name
    job_progress = Signal(str, int, int, str)     # job_name, done, total, message
    job_finished = Signal(str, object)            # job_name, summary
    job_error    = Signal(str, str)               # job_name, error_message
    idle         = Signal()
    library_changed = Signal()                    # debounced signal for model reload

    def __init__(
        self,
        parent=None,
        max_io_concurrency: int = 2,
        max_convert_concurrency: int = 1,
    ) -> None:
        super().__init__(parent)
        self.max_io_concurrency = max_io_concurrency
        self.max_convert_concurrency = max_convert_concurrency

        # Heavy lane (also blocked while a maintenance job runs)
        self._current_heavy_job: BaseJob | None = None
        self._heavy_queue: deque[BaseJob] = deque()

        # IO lane
        self._running_io_jobs: list[BaseJob] = []
        self._io_queue: deque[BaseJob] = deque()

        # Convert lane (one at a time by default)
        self._running_convert_jobs: list[BaseJob] = []
        self._convert_queue: deque[BaseJob] = deque()

        # Maintenance lane (exclusive: blocks heavy lane)
        self._current_maintenance_job: BaseJob | None = None
        self._maintenance_queue: deque[BaseJob] = deque()

        # Index lane (low-priority full-text indexing, 1 at a time)
        self.max_index_concurrency = 1
        self._running_index_jobs: list[BaseJob] = []
        self._index_queue: deque[BaseJob] = deque()

        # 300 ms debounce timer for library_changed
        self._change_timer = QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.setInterval(300)
        self._change_timer.timeout.connect(self.library_changed.emit)

    # ── Public API ─────────────────────────────────────────────────────────────

    def submit(self, job: BaseJob, lane: str | None = None) -> None:
        """Enqueue or run a job in its designated lane."""
        job_lane = lane or getattr(job, "lane", "heavy")
        job.lane = job_lane

        if job_lane == "io":
            if len(self._running_io_jobs) < self.max_io_concurrency:
                self._start_io_job(job)
            else:
                self._io_queue.append(job)
                logger.info("IO job '%s' enqueued (running: %d)", job.name, len(self._running_io_jobs))

        elif job_lane == "convert":
            if len(self._running_convert_jobs) < self.max_convert_concurrency:
                self._start_convert_job(job)
            else:
                self._convert_queue.append(job)
                logger.info("Convert job '%s' enqueued (running: %d)", job.name, len(self._running_convert_jobs))

        elif job_lane == "index":
            if len(self._running_index_jobs) < self.max_index_concurrency:
                self._start_index_job(job)
            else:
                self._index_queue.append(job)
                logger.info("Index job '%s' enqueued (running: %d)", job.name, len(self._running_index_jobs))

        elif job_lane == "maintenance":
            if self._current_maintenance_job is None and self._current_heavy_job is None:
                self._start_maintenance_job(job)
            else:
                self._maintenance_queue.append(job)
                logger.info("Maintenance job '%s' enqueued", job.name)

        else:  # heavy
            # Do not start heavy jobs while a maintenance job is active
            if self._current_heavy_job is None and self._current_maintenance_job is None:
                self._start_heavy_job(job)
            else:
                self._heavy_queue.append(job)
                logger.info("Heavy job '%s' enqueued (current: '%s')",
                            job.name,
                            (self._current_heavy_job or self._current_maintenance_job).name)

    def current_job(self) -> BaseJob | None:
        """Return currently active heavy/maintenance job, or first IO/convert/index job."""
        return (self._current_heavy_job
                or self._current_maintenance_job
                or (self._running_io_jobs[0] if self._running_io_jobs else None)
                or (self._running_convert_jobs[0] if self._running_convert_jobs else None)
                or (self._running_index_jobs[0] if self._running_index_jobs else None))

    def is_maintenance_active(self) -> bool:
        """True while a maintenance-lane job is running (blocks cleanup jobs)."""
        return self._current_maintenance_job is not None

    def has_pending_jobs(self, lane: str | None = None) -> bool:
        """Return True if there are running or queued jobs in the specified lane (or any lane)."""
        if lane == "index":
            return bool(self._running_index_jobs or self._index_queue)
        elif lane == "io":
            return bool(self._running_io_jobs or self._io_queue)
        elif lane == "convert":
            return bool(self._running_convert_jobs or self._convert_queue)
        elif lane == "maintenance":
            return bool(self._current_maintenance_job or self._maintenance_queue)
        elif lane == "heavy":
            return bool(self._current_heavy_job or self._heavy_queue)
        return bool(
            self._current_heavy_job or self._heavy_queue
            or self._running_io_jobs or self._io_queue
            or self._running_convert_jobs or self._convert_queue
            or self._current_maintenance_job or self._maintenance_queue
            or self._running_index_jobs or self._index_queue
        )

    def cancel_current(self) -> None:
        if self._current_heavy_job:
            self._current_heavy_job.cancel()
        if self._current_maintenance_job:
            self._current_maintenance_job.cancel()
        for j in self._running_io_jobs:
            j.cancel()
        for j in self._running_convert_jobs:
            j.cancel()
        for j in self._running_index_jobs:
            j.cancel()

    # ── Internal starters ──────────────────────────────────────────────────────

    def _start_heavy_job(self, job: BaseJob) -> None:
        self._current_heavy_job = job
        self._attach_signals(job)
        self.job_started.emit(job.name)
        job.start()

    def _start_io_job(self, job: BaseJob) -> None:
        self._running_io_jobs.append(job)
        self._attach_signals(job)
        self.job_started.emit(job.name)
        job.start()

    def _start_convert_job(self, job: BaseJob) -> None:
        self._running_convert_jobs.append(job)
        self._attach_signals(job)
        self.job_started.emit(job.name)
        job.start()

    def _start_index_job(self, job: BaseJob) -> None:
        self._running_index_jobs.append(job)
        self._attach_signals(job)
        self.job_started.emit(job.name)
        job.start()

    def _start_maintenance_job(self, job: BaseJob) -> None:
        self._current_maintenance_job = job
        self._attach_signals(job)
        self.job_started.emit(job.name)
        job.start()

    def _attach_signals(self, job: BaseJob) -> None:
        job.progress.connect(lambda d, t, m: self.job_progress.emit(job.name, d, t, m))
        job.error.connect(lambda ctx, err: self.job_error.emit(job.name, f"{ctx}: {err}"))
        job.data_changed.connect(self._on_data_changed)
        job.finished.connect(lambda res: self._on_job_finished(job, res))

    def _on_job_finished(self, job: BaseJob, summary: Any) -> None:
        logger.info("Job '%s' finished (lane: %s)", job.name, job.lane)
        self.job_finished.emit(job.name, summary)

        lane = job.lane

        if lane == "io":
            if job in self._running_io_jobs:
                self._running_io_jobs.remove(job)
            if self._io_queue:
                self._start_io_job(self._io_queue.popleft())

        elif lane == "convert":
            if job in self._running_convert_jobs:
                self._running_convert_jobs.remove(job)
            if self._convert_queue:
                self._start_convert_job(self._convert_queue.popleft())

        elif lane == "index":
            if job in self._running_index_jobs:
                self._running_index_jobs.remove(job)
            if self._index_queue:
                self._start_index_job(self._index_queue.popleft())

        elif lane == "maintenance":
            self._current_maintenance_job = None
            # Maintenance done: drain pending heavy jobs first, then check maintenance queue
            if self._maintenance_queue:
                self._start_maintenance_job(self._maintenance_queue.popleft())
            elif self._heavy_queue:
                self._start_heavy_job(self._heavy_queue.popleft())

        else:  # heavy
            self._current_heavy_job = None
            # Check whether a maintenance job was waiting
            if self._maintenance_queue:
                self._start_maintenance_job(self._maintenance_queue.popleft())
            elif self._heavy_queue:
                self._start_heavy_job(self._heavy_queue.popleft())

        # Check overall idle
        if (self._current_heavy_job is None
                and self._current_maintenance_job is None
                and not self._running_io_jobs
                and not self._running_convert_jobs
                and not self._running_index_jobs):
            self.idle.emit()

    def _on_data_changed(self) -> None:
        self._change_timer.start()


# Global singleton
_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
