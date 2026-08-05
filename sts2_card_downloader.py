"""
STS2 Card Downloader

Discovers cards on Untapped.gg by filtering the card listing by rarity
(via the `?rarity=` query param, paginating as needed), then visits each
card page, hovers to reveal the download control, and clicks it to save
the card artwork locally.

Usage:
  pip install -r requirements.txt
  playwright install chromium
  python3 sts2_card_downloader.py

Output: ./cards/<rarity>/*.png
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Literal

from playwright.async_api import (
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)
from pydantic import BaseModel, Field, HttpUrl, field_validator

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("sts2_card_downloader")

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# The wrapper that reveals a copy/download button pair on hover. Scoping to
# this (rather than searching the whole page) avoids matching unrelated
# "download the overlay app" nav/promo links elsewhere on the site.
_CARD_WRAPPER_SELECTOR = '[class*="HoverCopyButton-module-scss-module"][class*="container"]'
_DOWNLOAD_BUTTON_SELECTOR = 'button:has(i.fa-arrow-down-to-line)'


class _NoDownloadButton(Exception):
    pass


class DownloaderConfig(BaseModel):
    listing_url: HttpUrl = HttpUrl("https://sts2.untapped.gg/en/cards")
    card_base_url: HttpUrl = HttpUrl("https://sts2.untapped.gg/en/cards/")
    output_dir: Path = Path("cards")
    rarities: list[str] = Field(default_factory=lambda: ["ancient"])
    max_cards_per_rarity: int | None = None
    max_listing_pages: int = 20
    headless: bool = False
    overwrite: bool = False
    nav_timeout_ms: int = 15_000
    card_visible_timeout_ms: int = 10_000
    download_button_timeout_ms: int = 8_000
    download_timeout_ms: int = 10_000
    listing_settle_ms: int = 1_000
    inter_card_delay_ms: int = 1_000
    max_attempts_per_card: int = 2

    @field_validator("rarities")
    @classmethod
    def _rarities_valid_and_nonempty(cls, rarities: list[str]) -> list[str]:
        if not rarities:
            raise ValueError("rarities must contain at least one value")
        bad = [r for r in rarities if not _SLUG_RE.match(r)]
        if bad:
            raise ValueError(f"invalid rarity value(s), expected kebab-case: {bad}")
        return rarities

    def card_url(self, slug: str) -> str:
        return f"{str(self.card_base_url).rstrip('/')}/{slug}"

    def listing_page_url(self, rarity: str, page: int) -> str:
        url = f"{str(self.listing_url).rstrip('/')}?rarity={rarity}"
        if page > 1:
            url += f"&page={page}"
        return url

    def output_path(self, rarity: str, slug: str) -> Path:
        return self.output_dir / rarity / f"{slug}.png"


class CardResult(BaseModel):
    rarity: str
    slug: str
    status: Literal["downloaded", "skipped", "no_button", "timeout", "error"]
    path: Path | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("downloaded", "skipped")


class RunSummary(BaseModel):
    results: list[CardResult] = Field(default_factory=list)

    @property
    def succeeded(self) -> list[CardResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> list[CardResult]:
        return [r for r in self.results if not r.ok]

    def report(self) -> str:
        lines = [f"Done: {len(self.succeeded)} ok, {len(self.failed)} failed"]
        for r in self.failed:
            lines.append(f"  FAILED {r.rarity}/{r.slug}: {r.status} ({r.detail})")
        return "\n".join(lines)


class CardDownloader:
    def __init__(self, page: Page, config: DownloaderConfig) -> None:
        self.page = page
        self.config = config

    async def discover_slugs(self, rarity: str) -> list[str]:
        slugs: list[str] = []
        seen: set[str] = set()

        for page_num in range(1, self.config.max_listing_pages + 1):
            url = self.config.listing_page_url(rarity, page_num)
            logger.info("Discovering %s cards (page %d) ...", rarity, page_num)
            await self.page.goto(url, wait_until="domcontentloaded", timeout=self.config.nav_timeout_ms)
            await self.page.wait_for_timeout(self.config.listing_settle_ms)

            links = self.page.locator('a[href^="/en/cards/"]')
            found_new = False
            for i in range(await links.count()):
                href = await links.nth(i).get_attribute("href")
                slug = (href or "").rsplit("/", 1)[-1]
                if slug and slug not in seen:
                    seen.add(slug)
                    slugs.append(slug)
                    found_new = True

            has_next_page = await self.page.locator('button[aria-label="Next page"]').count() > 0
            if not has_next_page or not found_new:
                break

        logger.info("Discovered %d %s card(s)", len(slugs), rarity)
        return slugs

    async def download_card(self, rarity: str, slug: str) -> CardResult:
        out_path = self.config.output_path(rarity, slug)
        if out_path.exists() and not self.config.overwrite:
            logger.info("Skipping %s/%s (already exists)", rarity, slug)
            return CardResult(rarity=rarity, slug=slug, status="skipped", path=out_path)

        last_error: str | None = None
        for attempt in range(1, self.config.max_attempts_per_card + 1):
            try:
                return await self._attempt_download(rarity, slug, out_path)
            except _NoDownloadButton:
                return CardResult(rarity=rarity, slug=slug, status="no_button")
            except PlaywrightTimeoutError as e:
                last_error = str(e)
                logger.warning(
                    "  Attempt %d/%d timed out for %s/%s",
                    attempt, self.config.max_attempts_per_card, rarity, slug,
                )
            except Exception as e:  # noqa: BLE001 - reported in the run summary
                last_error = str(e)
                logger.warning(
                    "  Attempt %d/%d errored for %s/%s: %s",
                    attempt, self.config.max_attempts_per_card, rarity, slug, e,
                )

        status: Literal["timeout", "error"] = (
            "timeout" if last_error and "Timeout" in last_error else "error"
        )
        return CardResult(rarity=rarity, slug=slug, status=status, detail=last_error)

    async def _attempt_download(self, rarity: str, slug: str, out_path: Path) -> CardResult:
        url = self.config.card_url(slug)
        logger.info("Loading: %s/%s ...", rarity, slug)
        await self.page.goto(url, wait_until="domcontentloaded", timeout=self.config.nav_timeout_ms)

        card_locator = self.page.locator(_CARD_WRAPPER_SELECTOR).first
        await card_locator.wait_for(state="visible", timeout=self.config.card_visible_timeout_ms)
        await card_locator.hover()

        download_btn = card_locator.locator(_DOWNLOAD_BUTTON_SELECTOR).first
        try:
            await download_btn.wait_for(
                state="visible", timeout=self.config.download_button_timeout_ms
            )
        except PlaywrightTimeoutError:
            await self._log_visible_buttons(card_locator)
            raise _NoDownloadButton(slug)

        async with self.page.expect_download(timeout=self.config.download_timeout_ms) as dl_info:
            await download_btn.click()
        download = await dl_info.value

        out_path.parent.mkdir(parents=True, exist_ok=True)
        await download.save_as(out_path)
        logger.info("  Saved: %s", out_path)
        return CardResult(rarity=rarity, slug=slug, status="downloaded", path=out_path)

    async def _log_visible_buttons(self, card_locator: Locator) -> None:
        logger.warning("  NO DOWNLOAD BUTTON FOUND near card")
        items = await card_locator.locator("button, a, i").all()
        for item in items[:20]:
            try:
                cls = await item.get_attribute("class") or ""
                text = (await item.text_content() or "").strip()[:40]
                logger.warning('    class="%s" text="%s"', cls[:100], text)
            except Exception:
                continue


async def run(config: DownloaderConfig) -> RunSummary:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    summary = RunSummary()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.headless)
        try:
            context = await browser.new_context(
                accept_downloads=True,
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            downloader = CardDownloader(page, config)

            for rarity in config.rarities:
                slugs = await downloader.discover_slugs(rarity)
                if config.max_cards_per_rarity is not None:
                    slugs = slugs[: config.max_cards_per_rarity]

                for slug in slugs:
                    result = await downloader.download_card(rarity, slug)
                    summary.results.append(result)
                    await page.wait_for_timeout(config.inter_card_delay_ms)
        finally:
            await browser.close()

    return summary


def main() -> None:
    # Debugging with a single card first; set max_cards_per_rarity=None once verified.
    config = DownloaderConfig(rarities=["ancient"], max_cards_per_rarity=1)
    summary = asyncio.run(run(config))
    print()
    print(summary.report())
    print(f"Cards saved to: {config.output_dir.resolve()}")


if __name__ == "__main__":
    main()
