"""
reader/render.py – Dedicated rendering thread, memory cache, prefetching, and cancellation.

Adheres strictly to the concurrency model:
- All PyMuPDF rendering happens on one dedicated render thread.
- Progressive rendering & generation counter for cancellation of stale requests.
- LRU memory cache with 256 MB cap.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QMutex, QMutexLocker, QObject, QThread, QWaitCondition, Signal
from PySide6.QtGui import QImage

from booklib.reader.backend import DocumentBackend

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_CAP_BYTES = 256 * 1024 * 1024  # 256 MB


def quantize_zoom(zoom: float) -> float:
    """Quantize zoom level to 5% steps to prevent caching explosion."""
    return round(zoom * 20.0) / 20.0


@dataclass(frozen=True)
class RenderKey:
    page: int
    zoom_step: float
    dpr: float
    invert: bool
    sepia: bool
    layout_key: str


class LRUPageCache:
    """Thread-safe in-memory LRU cache of rendered page QImages."""

    def __init__(self, max_bytes: int = _DEFAULT_CACHE_CAP_BYTES) -> None:
        self.max_bytes = max_bytes
        self.current_bytes = 0
        self._cache: OrderedDict[RenderKey, QImage] = OrderedDict()
        self._lock = QMutex()

    def get(self, key: RenderKey) -> QImage | None:
        with QMutexLocker(self._lock):
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: RenderKey, image: QImage) -> None:
        if image.isNull():
            return
        img_size = image.sizeInBytes()
        with QMutexLocker(self._lock):
            if key in self._cache:
                self.current_bytes -= self._cache[key].sizeInBytes()
                del self._cache[key]

            while self._cache and (self.current_bytes + img_size > self.max_bytes):
                _, old_img = self._cache.popitem(last=False)
                self.current_bytes -= old_img.sizeInBytes()

            self._cache[key] = image
            self.current_bytes += img_size

    def clear(self) -> None:
        with QMutexLocker(self._lock):
            self._cache.clear()
            self.current_bytes = 0


@dataclass
class RenderTask:
    page: int
    zoom: float
    dpr: float
    invert: bool
    sepia: bool
    layout_key: str
    generation: int
    is_prefetch: bool = False


class RenderWorker(QThread):
    """
    Dedicated background render thread owning the DocumentBackend.
    Executes render requests and notifies UI thread via signals.
    """

    page_rendered = Signal(int, QImage, int)  # page, image, generation
    error_occurred = Signal(int, str)         # page, error_message

    def __init__(self, backend: DocumentBackend, cache: LRUPageCache | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.cache = cache or LRUPageCache()
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._queue: list[RenderTask] = []
        self._running = True
        self._current_generation = 0

    def set_generation(self, gen: int) -> None:
        """Bump generation to drop obsolete tasks."""
        with QMutexLocker(self._mutex):
            self._current_generation = gen
            # Drop older non-prefetch tasks
            self._queue = [t for t in self._queue if t.generation >= gen]

    def request_page(
        self,
        page: int,
        zoom: float,
        dpr: float = 1.0,
        invert: bool = False,
        sepia: bool = False,
        layout_key: str = "",
        generation: int = 0,
        is_prefetch: bool = False,
    ) -> None:
        """Request rendering of a page. Emits immediately if cached."""
        qz = quantize_zoom(zoom)
        key = RenderKey(
            page=page,
            zoom_step=qz,
            dpr=dpr,
            invert=invert,
            sepia=sepia,
            layout_key=layout_key,
        )
        cached = self.cache.get(key)
        if cached is not None:
            self.page_rendered.emit(page, cached, generation)
            return

        task = RenderTask(
            page=page,
            zoom=qz,
            dpr=dpr,
            invert=invert,
            sepia=sepia,
            layout_key=layout_key,
            generation=generation,
            is_prefetch=is_prefetch,
        )

        with QMutexLocker(self._mutex):
            # Prioritize interactive tasks over prefetch
            if is_prefetch:
                self._queue.append(task)
            else:
                self._queue.insert(0, task)
            self._cond.wakeOne()

    def run(self) -> None:
        """Worker thread render loop."""
        while True:
            with QMutexLocker(self._mutex):
                while not self._queue and self._running:
                    self._cond.wait(self._mutex)

                if not self._running:
                    break

                task = self._queue.pop(0)
                gen = self._current_generation

            # Cancel task if stale
            if task.generation < gen and not task.is_prefetch:
                continue

            key = RenderKey(
                page=task.page,
                zoom_step=task.zoom,
                dpr=task.dpr,
                invert=task.invert,
                sepia=task.sepia,
                layout_key=task.layout_key,
            )

            # Check cache again
            cached = self.cache.get(key)
            if cached is not None:
                self.page_rendered.emit(task.page, cached, task.generation)
                continue

            try:
                img = self.backend.render(
                    task.page,
                    task.zoom,
                    dpr=task.dpr,
                    invert=task.invert,
                    sepia=task.sepia,
                )
                if not img.isNull():
                    self.cache.put(key, img)
                    self.page_rendered.emit(task.page, img, task.generation)
            except Exception as exc:
                logger.warning("Render worker failed for page %d: %s", task.page, exc)
                self.error_occurred.emit(task.page, str(exc))

    def stop(self) -> None:
        """Stop worker thread and wait for exit."""
        with QMutexLocker(self._mutex):
            self._running = False
            self._queue.clear()
            self._cond.wakeAll()
        self.wait(2000)
