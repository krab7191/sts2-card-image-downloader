# STS2 Card Downloader

Browser automation script that visits each card page on
[sts2.untapped.gg](https://sts2.untapped.gg) and downloads the card
artwork, using Playwright to drive a real Chromium browser.

Cards are organized by rarity in `CARDS_BY_RARITY` (currently just
`ancient`; add `rare`, `uncommon`, etc. as slug lists once you have them).
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

`main()` currently runs a single card (`ancient/abundance`) for debugging.
Once a run looks right, change it to download everything:

```python
config = DownloaderConfig()  # uses the full CARDS_BY_RARITY
```

## How it works

For each `(rarity, slug)` pair:

1. Navigates to `https://sts2.untapped.gg/en/cards/<slug>`.
2. Waits for the card render container and hovers over it to reveal the
   download control.
3. Tries a list of selectors to find the download button; falls back to
   scanning nearby buttons/links for download-related text if none match.
4. Saves the resulting file to `cards/<rarity>/<slug>.png`.

Cards whose output file already exists are skipped (set `overwrite=True`
in `DownloaderConfig` to re-download). Failed cards are retried once and
summarized at the end of the run.

## Config

All tunables (timeouts, headless mode, output dir, overwrite behavior,
retries) live on the `DownloaderConfig` pydantic model in
`sts2_card_downloader.py` — construct one with overrides instead of
editing constants scattered through the script.

## Troubleshooting

If a card fails with `no_button`, the site's DOM likely changed. The
script logs every visible button/link it can see on that page (aria-label,
title, text, class) — use that to find the new selector and add it to
`DOWNLOAD_BUTTON_SELECTORS`.
