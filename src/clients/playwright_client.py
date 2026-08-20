from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright


class PlaywrightClient:
    """Браузерный клиент для страниц отзывов Metacritic (user/critic)."""

    def __init__(self, config: dict, logger) -> None:
        self.user_agent = config["http"]["user_agent"]
        self.timeout = config["http"]["timeout"] * 1000
        self.logger = logger

    async def _open_page(self, playwright, url: str):
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=self.user_agent)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
            await page.wait_for_timeout(3000)
            await self._dismiss_cookie_banner(page)
            return browser, page
        except Exception:
            await browser.close()
            raise

    async def _dismiss_cookie_banner(self, page) -> None:
        """Закрывает cookie-баннер OneTrust и ждёт, пока он исчезнет."""
        banner = page.locator("#onetrust-consent-sdk")
        if await banner.count() == 0:
            return
        accept = page.locator("#onetrust-accept-btn-handler")
        if await accept.count() > 0:
            try:
                await accept.first.click(timeout=5000)
            except Exception:
                pass
        try:
            await banner.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass

    async def _ensure_no_cookie_banner(self, page) -> None:
        """Перед кликом по dropdown: если плашка снова видна — закрыть её ещё раз."""
        banner = page.locator("#onetrust-consent-sdk")
        if await banner.count() > 0 and await banner.is_visible():
            await self._dismiss_cookie_banner(page)

    async def get_platform_options(self, url: str) -> list[str]:
        async with async_playwright() as p:
            browser, page = await self._open_page(p, url)
            try:
                options = await page.locator('[data-testid="dropdown-v2-option"] span').all_text_contents()
                return [o.strip() for o in options if o.strip()]
            finally:
                await browser.close()

    async def get_reviews(self, url: str, platform_name: str, limit: int) -> str:
        async with async_playwright() as p:
            browser, page = await self._open_page(p, url)
            try:
                await page.locator('[data-testid="dropdown-v2-trigger"]').first.click(timeout=10000)
                await page.wait_for_timeout(500)
                await self._ensure_no_cookie_banner(page)
                option = page.locator('[data-testid="dropdown-v2-option"]', has_text=platform_name).first
                await option.click(timeout=10000)
                await page.wait_for_timeout(4000)
                cards = page.locator('[data-testid="review-card"]')
                count = min(await cards.count(), limit)
                html = ""
                for i in range(count):
                    html += await cards.nth(i).evaluate("el => el.outerHTML") + "\n"
                return html
            finally:
                await browser.close()
