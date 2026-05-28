"""
utils/browser.py – Playwright async browser manager.

Usage::

    async with BrowserManager() as bm:
        page = await bm.new_page()
        await page.goto("https://example.com")
        await bm.screenshot(page, "/tmp/shot.png")
"""

from __future__ import annotations

import logging
import os
import random
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# User-Agent rotation pool – 10 real desktop UA strings (2024–2025 era)
# ---------------------------------------------------------------------------

_USER_AGENTS: list[str] = [
    # Chrome 124 / Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    # Chrome 124 / macOS Sonoma
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    # Chrome 123 / Ubuntu
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36",
    # Firefox 125 / Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Firefox 124 / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",
    # Safari 17 / macOS Sonoma
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4.1 Safari/605.1.15",
    # Edge 124 / Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Chrome 122 / Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.6261.112 Safari/537.36",
    # Chrome 121 / macOS Ventura
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_6) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36",
    # Opera 108 / Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36 OPR/108.0.0.0",
]


class BrowserManager:
    """
    Async Playwright browser manager with User-Agent rotation.

    Supports ``async with`` syntax::

        async with BrowserManager() as bm:
            page = await bm.new_page()
            ...

    Or manual lifecycle::

        bm = BrowserManager()
        await bm.__aenter__()
        ...
        await bm.close()
    """

    def __init__(self, headless: Optional[bool] = None) -> None:
        """
        Parameters
        ----------
        headless:
            Override headless mode.  When *None* (default) the value is read
            from the ``HEADLESS_BROWSER`` environment variable (default ``True``).
        """
        if headless is None:
            env_val = os.environ.get("HEADLESS_BROWSER", "true").strip().lower()
            headless = env_val not in {"false", "0", "no", "off"}
        self._headless: bool = headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    # ------------------------------------------------------------------
    # Context-manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BrowserManager":
        await self._launch()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _launch(self) -> None:
        """Start Playwright and launch a Chromium browser instance."""
        if self._browser is not None:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        logger.info(
            "Browser launched (headless=%s, chromium %s)",
            self._headless,
            self._browser.version,
        )

    async def close(self) -> None:
        """Close the browser and stop Playwright (idempotent)."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error closing browser: %s", exc)
            finally:
                self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error stopping playwright: %s", exc)
            finally:
                self._playwright = None

    # ------------------------------------------------------------------
    # Page factory
    # ------------------------------------------------------------------

    async def new_page(self) -> Page:
        """
        Create a new browser page (tab) with a randomised User-Agent and
        common stealth viewport settings.

        Returns
        -------
        playwright.async_api.Page
        """
        if self._browser is None:
            await self._launch()

        ua = random.choice(_USER_AGENTS)
        # Vary viewport slightly to avoid fingerprinting
        width = random.randint(1280, 1920)
        height = random.randint(720, 1080)

        context: BrowserContext = await self._browser.new_context(  # type: ignore[union-attr]
            user_agent=ua,
            viewport={"width": width, "height": height},
            locale="en-US",
            timezone_id="America/Los_Angeles",
            java_script_enabled=True,
            # Prevent Playwright from exposing itself via navigator.webdriver
            bypass_csp=False,
        )

        # Patch navigator.webdriver to undefined
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page: Page = await context.new_page()
        logger.debug("New page created (UA=%s…, viewport=%dx%d)", ua[:40], width, height)
        return page

    # ------------------------------------------------------------------
    # Screenshot helper
    # ------------------------------------------------------------------

    async def screenshot(self, page: Page, path: str) -> None:
        """
        Save a full-page screenshot of *page* to *path*.

        Parameters
        ----------
        page:
            An active Playwright :class:`Page` instance.
        path:
            Absolute or relative filesystem path for the PNG output.
        """
        try:
            await page.screenshot(path=path, full_page=True)
            logger.info("Screenshot saved: %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.error("screenshot() failed (path=%s): %s", path, exc)
