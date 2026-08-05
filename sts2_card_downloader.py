"""
STS2 Card Downloader

Visits each card page on Untapped.gg, grouped by rarity (ancient, rare,
uncommon, ...), and clicks the download button to save the card artwork
locally.

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
    Download,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)
from pydantic import BaseModel, Field, HttpUrl, field_validator

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("sts2_card_downloader")

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

ANCIENT_CARDS = [
    "abundance", "apotheosis", "apparition", "biased-cognition", "break",
    "brightest-flame", "corruption", "forbidden-grimoire", "maul",
    "meteor-shower", "neows-fury", "protector", "quadcast", "relax",
    "suppress", "the-sealed-throne", "whistle", "wish", "wraith-form",
]

# Add more rarities here as slug lists become available, e.g.
# "rare": [...], "uncommon": [...].
CARDS_BY_RARITY: dict[str, list[str]] = {
    "ancient": ANCIENT_CARDS,
}

# Tried in order against the hover-revealed download control.
DOWNLOAD_BUTTON_SELECTORS = [
    'button[aria-label*="download" i]',
    'a[aria-label*="download" i]',
    'button[title*="download" i]',
    'a[title*="download" i]',
    '[role="button"][aria-label*="download" i]',
    '[role="button"][title*="download" i]',
    'button:has(i.fa-download)',
    'button:has(svg[class*="download" i])',
    'a:has(i.fa-download)',
    'a:has(svg[class*="download" i])',
    '[data-tooltip*="download" i]',
    '[tooltip*="download" i]',
]


class _NoDownloadButton(Exception):
    pass


class DownloaderConfig(BaseModel):
    base_url: HttpUrl = HttpUrl("https://sts2.untapped.gg/en/cards/")
    output_dir: Path = Path("cards")
    cards_by_rarity: dict[str, list[str]] = Field(
        default_factory=lambda: dict(CARDS_BY_RARITY)
    )
    headless: bool = False
    overwrite: bool = False
    nav_timeout_ms: int = 15_000
    card_visible_timeout_ms: int = 10_000
    button_probe_timeout_ms: int = 1_000
    download_timeout_ms: int = 10_000
    hover_settle_ms: int = 500
    inter_card_delay_ms: int = 1_000
    max_attempts_per_card: int = 2

    @field_validator("cards_by_rarity")
    @classmethod
    def _cards_valid_and_nonempty(cls, cards: dict[str, list[str]]) -> dict[str, list[str]]:
        if not cards:
            raise ValueError("cards_by_rarity must contain at least one rarity")
        for rarity, slugs in cards.items():
            if not _SLUG_RE.match(rarity):
                raise ValueError(f"invalid rarity name, expected kebab-case: {rarity!r}")
            if not slugs:
                raise ValueError(f"rarity {rarity!r} has no card slugs")
            bad = [s for s in slugs if not _SLUG_RE.match(s)]
            if bad:
                raise ValueError(f"invalid slug(s) for rarity {rarity!r}: {bad}")
        return cards

    def card_url(self, slug: str) -> str:
        return f"{str(self.base_url).rstrip('/')}/{slug}"

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
        await self.page.goto(
            url, wait_until="domcontentloaded", timeout=self.config.nav_timeout_ms
        )

        card_locator = self.page.locator('[class*="CardBuilder"]').first
        await card_locator.wait_for(
            state="visible", timeout=self.config.card_visible_timeout_ms
        )
        await card_locator.hover()
        await self.page.wait_for_timeout(self.config.hover_settle_ms)

        download = await self._trigger_download(card_locator)
        if download is None:
            await self._log_visible_buttons()
            raise _NoDownloadButton(slug)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        await download.save_as(out_path)
        logger.info("  Saved: %s", out_path)
        return CardResult(rarity=rarity, slug=slug, status="downloaded", path=out_path)

    async def _trigger_download(self, card_locator: Locator) -> Download | None:
        for sel in DOWNLOAD_BUTTON_SELECTORS:
            btn = self.page.locator(sel).first
            try:
                visible = await btn.is_visible(timeout=self.config.button_probe_timeout_ms)
            except PlaywrightTimeoutError:
                continue
            if not visible:
                continue
            async with self.page.expect_download(
                timeout=self.config.download_timeout_ms
            ) as dl_info:
                await btn.click()
            logger.info("  Clicked: %s", sel)
            return await dl_info.value

        return await self._trigger_download_fallback(card_locator)

    async def _trigger_download_fallback(self, card_locator: Locator) -> Download | None:
        card_box = await card_locator.bounding_box()
        if not card_box:
            return None

        candidates = await self.page.locator('button, a, [role="button"]').all()
        for item in candidates:
            try:
                box = await item.bounding_box()
                if not box:
                    continue
                if abs(box["x"] - card_box["x"]) >= 300 or abs(box["y"] - card_box["y"]) >= 400:
                    continue
                aria = await item.get_attribute("aria-label") or ""
                title = await item.get_attribute("title") or ""
                text = (await item.text_content() or "").strip()
                if "download" not in (aria + title + text).lower():
                    continue
                async with self.page.expect_download(
                    timeout=self.config.download_timeout_ms
                ) as dl_info:
                    await item.click()
                logger.info(
                    '  Clicked fallback: aria="%s" title="%s" text="%s"', aria, title, text
                )
                return await dl_info.value
            except Exception:
                continue
        return None

    async def _log_visible_buttons(self) -> None:
        logger.warning("  NO DOWNLOAD BUTTON FOUND")
        items = await self.page.locator('button, a, [role="button"]').all()
        for item in items[:20]:
            try:
                if not await item.is_visible():
                    continue
                aria = await item.get_attribute("aria-label") or ""
                title = await item.get_attribute("title") or ""
                text = (await item.text_content() or "").strip()[:40]
                cls = await item.get_attribute("class") or ""
                if aria or title or text:
                    logger.warning(
                        '    aria="%s" title="%s" text="%s" class="%s"',
                        aria, title, text, cls[:60],
                    )
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

            for rarity, slugs in config.cards_by_rarity.items():
                for slug in slugs:
                    result = await downloader.download_card(rarity, slug)
                    summary.results.append(result)
                    await page.wait_for_timeout(config.inter_card_delay_ms)
        finally:
            await browser.close()

    return summary


def main() -> None:
    # Debugging with a single card first; switch to CARDS_BY_RARITY once verified.
    config = DownloaderConfig(cards_by_rarity={"ancient": ANCIENT_CARDS[:1]})
    summary = asyncio.run(run(config))
    print()
    print(summary.report())
    print(f"Cards saved to: {config.output_dir.resolve()}")


if __name__ == "__main__":
    main()
