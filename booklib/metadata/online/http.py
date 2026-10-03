"""
http.py – Shared HTTP session, rate limiting, retries, and offline detection.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any
import requests

from booklib.db import repository

logger = logging.getLogger(__name__)


class OfflineError(Exception):
    """Raised when consecutive connection errors indicate no network access."""
    pass


class RateLimiter:
    """Thread-safe rate limiter that enforces a minimum interval between requests."""

    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval
        self._last_call = 0.0

    def wait(self) -> None:
        now = time.time()
        elapsed = now - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.time()


class HttpClient:
    """
    HTTP client wrapper handling:
    - User-Agent header
    - Per-provider rate limiting
    - Retries on 429 and 5xx with exponential backoff
    - Offline detection (stopping after 3 consecutive network failures)
    - SQLite response caching
    """

    def __init__(
        self,
        provider_name: str,
        user_agent: str = "BookLib/3.0 (https://github.com/booklib)",
        rate_limit_sec: float = 1.0,
        timeout: tuple[float, float] = (5.0, 15.0),
    ):
        self.provider_name = provider_name
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
        self.limiter = RateLimiter(min_interval=rate_limit_sec)
        self.timeout = timeout
        self._consecutive_errors = 0
        self.max_consecutive_errors = 3

    def reset_offline_counter(self) -> None:
        self._consecutive_errors = 0

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        cache_key: str | None = None,
        db_conn: Any = None,
    ) -> Any | None:
        """
        Perform a GET request expecting JSON.
        Checks and updates SQLite cache if cache_key and db_conn are provided.
        Raises OfflineError if network is down.
        Returns parsed JSON or None.
        """
        # Check cache
        if cache_key and db_conn is not None:
            try:
                cached_str = repository.get_online_cache(db_conn, cache_key, max_age_days=30)
                if cached_str is not None:
                    data = json.loads(cached_str)
                    if isinstance(data, dict) and data.get("__not_found__"):
                        return None
                    return data
            except Exception as e:
                logger.debug("Cache read error for %s: %s", cache_key, e)

        # Make network request
        if self._consecutive_errors >= self.max_consecutive_errors:
            raise OfflineError(f"Network appears offline ({self._consecutive_errors} consecutive failures).")

        max_tries = 3
        delay = 1.0

        for attempt in range(1, max_tries + 1):
            self.limiter.wait()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                self._consecutive_errors += 1
                logger.warning(
                    "Network error (%d/%d) calling %s: %s",
                    attempt,
                    max_tries,
                    url,
                    exc,
                )
                if self._consecutive_errors >= self.max_consecutive_errors:
                    raise OfflineError(f"Network offline: {exc}") from exc
                if attempt < max_tries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                return None
            except requests.exceptions.RequestException as exc:
                logger.warning("Request exception for %s: %s", url, exc)
                return None

            # Handle response
            if resp.status_code == 200:
                self._consecutive_errors = 0
                try:
                    data = resp.json()
                except Exception as e:
                    logger.warning("Failed to decode JSON from %s: %s", url, e)
                    return None

                # Write to cache
                if cache_key and db_conn is not None:
                    try:
                        repository.set_online_cache(db_conn, cache_key, self.provider_name, json.dumps(data))
                    except Exception as e:
                        logger.debug("Cache write error for %s: %s", cache_key, e)
                return data

            if resp.status_code == 404:
                # Cache 404 as not found
                if cache_key and db_conn is not None:
                    try:
                        repository.set_online_cache(
                            db_conn, cache_key, self.provider_name, json.dumps({"__not_found__": True})
                        )
                    except Exception:
                        pass
                return None

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                retry_after_str = resp.headers.get("Retry-After")
                if retry_after_str and retry_after_str.isdigit():
                    wait_time = float(retry_after_str)
                else:
                    wait_time = delay
                logger.warning("HTTP %d from %s; waiting %.1fs", resp.status_code, url, wait_time)
                if attempt < max_tries:
                    time.sleep(wait_time)
                    delay *= 2
                    continue
                return None

            # Other status code (e.g. 400, 403)
            logger.warning("HTTP %d from %s: %s", resp.status_code, url, resp.text[:200])
            return None

        return None
