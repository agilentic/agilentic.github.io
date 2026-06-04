"""
utils/rate_limiter.py – Per-platform async rate limiter with jitter.

Design
------
* One :class:`asyncio.Lock` per platform prevents concurrent callers from
  racing each other and double-firing.
* Default rate: 1 request every 2 seconds + ±0.5 s uniform jitter.
* ``set_pause()`` suspends a platform for *N* seconds (e.g. after a CAPTCHA).

Usage::

    limiter = RateLimiter()

    # In your scraping coroutines:
    await limiter.acquire("linkedin")
    # … make the HTTP / Playwright request …

    # When a CAPTCHA is detected:
    limiter.set_pause("linkedin", 7200)   # pause for 2 hours
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_INTERVAL_S: float = 2.0     # minimum seconds between requests
_DEFAULT_JITTER_S: float = 0.5       # uniform jitter: ±0.5 s


# ---------------------------------------------------------------------------
# Per-platform state
# ---------------------------------------------------------------------------

@dataclass
class _PlatformState:
    """Mutable state for a single platform."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_request_at: float = 0.0          # monotonic timestamp of last release
    pause_until: float = 0.0              # monotonic timestamp; 0 → no pause


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """
    Async, per-platform rate limiter with configurable interval and jitter.

    Parameters
    ----------
    interval_s:
        Minimum number of seconds to wait between consecutive requests to the
        same platform (default: 2.0 s).
    jitter_s:
        Half-width of the uniform jitter window added to each wait
        (default: 0.5 s).  The actual extra wait is drawn from
        ``Uniform(-jitter_s, +jitter_s)``.

    Examples
    --------
    ::

        limiter = RateLimiter(interval_s=3.0, jitter_s=1.0)
        await limiter.acquire("indeed")
        # make request …

        # CAPTCHA hit – cool down for 2 hours
        limiter.set_pause("indeed", 7200)
    """

    def __init__(
        self,
        interval_s: float = _DEFAULT_INTERVAL_S,
        jitter_s: float = _DEFAULT_JITTER_S,
    ) -> None:
        self._interval_s = interval_s
        self._jitter_s = jitter_s
        self._platforms: Dict[str, _PlatformState] = {}
        # A meta-lock protects lazy initialisation of per-platform state
        self._init_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_state(self, platform: str) -> _PlatformState:
        """Return (creating if necessary) the state object for *platform*."""
        if platform not in self._platforms:
            async with self._init_lock:
                # Double-checked locking
                if platform not in self._platforms:
                    self._platforms[platform] = _PlatformState()
        return self._platforms[platform]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(self, platform: str) -> None:
        """
        Block the calling coroutine until it is safe to issue the next
        request to *platform*.

        Enforces:

        1. A per-platform asyncio lock so only one caller proceeds at a time.
        2. A mandatory pause if ``set_pause()`` was called.
        3. The configured minimum interval + random jitter between successive
           requests.

        Parameters
        ----------
        platform:
            Arbitrary platform identifier (e.g. ``"linkedin"``, ``"indeed"``).
        """
        state = await self._get_state(platform)

        async with state.lock:
            now = time.monotonic()

            # ── 1. Honour any active pause (e.g. post-CAPTCHA cool-down) ──
            if state.pause_until > now:
                remaining = state.pause_until - now
                logger.info(
                    "RateLimiter: platform '%s' is paused for %.1f more seconds.",
                    platform,
                    remaining,
                )
                await asyncio.sleep(remaining)
                now = time.monotonic()

            # ── 2. Enforce minimum interval + jitter ──
            elapsed = now - state.last_request_at
            jitter = random.uniform(-self._jitter_s, self._jitter_s)
            required_wait = self._interval_s + jitter

            if elapsed < required_wait:
                sleep_for = required_wait - elapsed
                logger.debug(
                    "RateLimiter: sleeping %.2fs for platform '%s'.",
                    sleep_for,
                    platform,
                )
                await asyncio.sleep(sleep_for)

            # ── 3. Record release time ──
            state.last_request_at = time.monotonic()
            logger.debug("RateLimiter: acquired for platform '%s'.", platform)

    def set_pause(self, platform: str, seconds: int) -> None:
        """
        Pause *platform* for *seconds* seconds starting from right now.

        Any in-flight ``acquire()`` call for that platform will honour the
        pause as soon as it reaches the pause-check inside the lock.

        This method is **synchronous** and safe to call from non-async code.

        Parameters
        ----------
        platform:
            Platform identifier to pause.
        seconds:
            Duration of the pause in seconds (e.g. 7200 for 2 hours).
        """
        # Ensure the state object exists (synchronous path – use dict directly)
        if platform not in self._platforms:
            # Best-effort: if the event loop is running we cannot await here,
            # so we create the state synchronously without a lock.  The
            # _init_lock is only needed for concurrent async init; a single
            # synchronous creator is fine.
            self._platforms[platform] = _PlatformState()

        state = self._platforms[platform]
        state.pause_until = time.monotonic() + seconds
        logger.warning(
            "RateLimiter: platform '%s' paused for %d seconds.",
            platform,
            seconds,
        )

    def clear_pause(self, platform: str) -> None:
        """
        Cancel any active pause for *platform* immediately.

        Parameters
        ----------
        platform:
            Platform identifier whose pause should be cleared.
        """
        if platform in self._platforms:
            self._platforms[platform].pause_until = 0.0
            logger.info("RateLimiter: pause cleared for platform '%s'.", platform)

    def status(self) -> dict[str, dict[str, float]]:
        """
        Return a snapshot of all tracked platform states for observability.

        Returns
        -------
        dict
            Keys are platform names; values are dicts with:

            - ``last_request_at`` – monotonic timestamp of the last request
            - ``pause_until`` – monotonic timestamp of pause expiry (0 if none)
            - ``pause_remaining_s`` – seconds left in the current pause (0 if none)
        """
        now = time.monotonic()
        return {
            name: {
                "last_request_at": state.last_request_at,
                "pause_until": state.pause_until,
                "pause_remaining_s": max(0.0, state.pause_until - now),
            }
            for name, state in self._platforms.items()
        }
