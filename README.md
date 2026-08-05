# STS2 Card Downloader

Browser automation script that discovers cards on
[sts2.untapped.gg](https://sts2.untapped.gg) by rarity and downloads the
card artwork, using Playwright to drive a real Chromium browser.

Output goes to `cards/<rarity>/<slug>.png`.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

(A `.venv` already exists in this repo if you're picking it up fresh —
just run `source .venv/bin/activate` and `pip install -r requirements.txt`.)

## Run

```bash
source .venv/bin/activate
python3 sts2_card_downloader.py
```

`main()` currently limits each rarity to 1 card for debugging. Once a run
looks right, remove the cap to download everything:

```python
config = DownloaderConfig(rarities=["ancient"])  # max_cards_per_rarity=None
```

Add more rarities as needed — no slug lists to maintain, they're
discovered live from the site:

```python
config = DownloaderConfig(rarities=["ancient", "rare", "uncommon", "common", "basic"])
```

## How it works

For each rarity:

1. Loads `https://sts2.untapped.gg/en/cards?rarity=<rarity>`, paginating
   with `&page=N` until the "Next page" button disappears, and collects
   every `/en/cards/<slug>` link to build the card list.
2. For each discovered slug, navigates to `https://sts2.untapped.gg/en/cards/<slug>`.
3. Hovers over the card to reveal its `HoverCopyButton` control (a
   copy-to-clipboard button and a download button appear side by side —
   the download button is the one with a `fa-arrow-down-to-line` icon).
4. Clicks the download button and saves the resulting file to
   `cards/<rarity>/<slug>.png`.

Cards whose output file already exists are skipped (set `overwrite=True`
in `DownloaderConfig` to re-download). Failed cards are retried once and
summarized at the end of the run.

## Config

All tunables (timeouts, headless mode, output dir, overwrite behavior,
retries, rarities, per-rarity card cap) live on the `DownloaderConfig`
pydantic model in `sts2_card_downloader.py` — construct one with
overrides instead of editing constants scattered through the script.

## Troubleshooting

If a card fails with `no_button`, the site's DOM likely changed. The
script logs every button/link/icon it finds near the card (class, text) —
use that to find the new markup and update `_CARD_WRAPPER_SELECTOR` /
`_DOWNLOAD_BUTTON_SELECTOR` near the top of the file.

If discovery finds 0 cards for a rarity, check that
`https://sts2.untapped.gg/en/cards?rarity=<rarity>` still uses that query
param and that the rarity value matches what the site's filter dropdown
uses internally (e.g. `ancient`, `rare`, `uncommon`, `common`, `basic`).
