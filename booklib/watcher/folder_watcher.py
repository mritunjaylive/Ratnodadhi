"""
folder_watcher.py – Folder watching via watchdog with debounce and file stability checks.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import queue
import time
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from booklib.config import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

_TEMP_EXTENSIONS = {".part", ".crdownload", ".tmp", ".download"}


def is_supported_file(path: str | Path) -> bool:
    p = Path(path)
    # Check hidden
    for part in p.parts:
        if part.startswith(".") and len(part) > 1:
            return False
    # Check suffix
    ext = p.suffix.lower()
    if ext.endswith("~") or ext in _TEMP_EXTENSIONS:
        return False
    clean_ext = ext.lstrip(".")
    return clean_ext in SUPPORTED_EXTENSIONS


def wait_until_stable(path: str | Path, timeout: float = 3.0) -> bool:
    """
    Check that a file has finished copying:
    - Size doesn't change for ~1 second.
    - Can be opened for reading.
    Returns True if stable, False if timed out or still locked.
    """
    p = Path(path)
    if not p.exists():
        return False

    deadline = time.time() + timeout
    last_size = -1

    while time.time() < deadline:
        try:
            curr_size = p.stat().st_size
            if curr_size == last_size and curr_size > 0:
                # Attempt to open for read
                with open(p, "rb") as f:
                    f.read(1)
                return True
            last_size = curr_size
        except (OSError, PermissionError):
            pass
        time.sleep(0.4)

    # Final check
    try:
        with open(p, "rb") as f:
            f.read(1)
        return True
    except Exception:
        return False


@dataclass
class WatchEvent:
    event_type: str  # 'created' | 'modified' | 'deleted' | 'moved'
    src_path: str
    dest_path: str | None = None


class _WatchdogHandler(FileSystemEventHandler):
    def __init__(self, event_queue: queue.Queue[WatchEvent], on_event_callback: Any):
        super().__init__()
        self.queue = event_queue
        self.on_event_callback = on_event_callback

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and is_supported_file(event.src_path):
            self.queue.put(WatchEvent("created", event.src_path))
            self.on_event_callback()

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and is_supported_file(event.src_path):
            self.queue.put(WatchEvent("modified", event.src_path))
            self.on_event_callback()

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and is_supported_file(event.src_path):
            self.queue.put(WatchEvent("deleted", event.src_path))
            self.on_event_callback()

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src_valid = is_supported_file(event.src_path)
            dest_valid = is_supported_file(event.dest_path)
            if src_valid or dest_valid:
                self.queue.put(WatchEvent("moved", event.src_path, event.dest_path))
                self.on_event_callback()


class FolderWatcher(QObject):
    """
    Watches directories using watchdog in a background thread.
    Emits batch_ready signal after 3 seconds of quiet on the UI thread.
    """
    batch_ready = Signal(list)  # list[WatchEvent]

    def __init__(self, debounce_ms: int = 3000, parent: QObject | None = None):
        super().__init__(parent)
        self.debounce_ms = debounce_ms
        self._observer: Observer | None = None
        self._watched_paths: dict[str, Any] = {}
        self._queue: queue.Queue[WatchEvent] = queue.Queue()
        self._own_changes: set[str] = set()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.debounce_ms)
        self._timer.timeout.connect(self._on_timer_timeout)

    def add_own_change(self, path: str | Path) -> None:
        """Register a path modified by the app so the watcher ignores it once."""
        self._own_changes.add(str(Path(path).resolve()))

    def _notify_event(self) -> None:
        # Restart debounce timer
        self._timer.start()

    def start(self) -> None:
        if self._observer is None:
            self._observer = Observer()
            self._observer.daemon = True
            self._observer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
        self._watched_paths.clear()

    def add_folder(self, folder_path: str) -> bool:
        if not os.path.exists(folder_path):
            return False
        if folder_path in self._watched_paths:
            return True

        self.start()
        handler = _WatchdogHandler(self._queue, self._notify_event)
        try:
            watch = self._observer.schedule(handler, folder_path, recursive=True)
            self._watched_paths[folder_path] = watch
            return True
        except Exception as exc:
            logger.warning("Failed to watch folder %s: %s", folder_path, exc)
            return False

    def remove_folder(self, folder_path: str) -> None:
        watch = self._watched_paths.pop(folder_path, None)
        if watch and self._observer:
            try:
                self._observer.unschedule(watch)
            except Exception:
                pass

    def _on_timer_timeout(self) -> None:
        events: list[WatchEvent] = []
        while not self._queue.empty():
            try:
                ev = self._queue.get_nowait()
                events.append(ev)
            except queue.Empty:
                break

        if not events:
            return

        # Deduplicate events for the same path and filter own-changes
        final_events: list[WatchEvent] = []
        seen_paths: set[str] = set()
        for ev in reversed(events):
            target = ev.dest_path if ev.dest_path else ev.src_path
            target_resolved = str(Path(target).resolve())
            if target_resolved in self._own_changes:
                self._own_changes.discard(target_resolved)
                continue
            if target not in seen_paths:
                seen_paths.add(target)
                final_events.append(ev)

        final_events.reverse()
        if final_events:
            self.batch_ready.emit(final_events)
