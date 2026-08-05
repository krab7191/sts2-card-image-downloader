"""
Print Set Builder

Runs every downloaded card (cards/<rarity>/<slug>[-upgraded].png) through
the postprocessing pipeline into finished_cards/ (one processed file per
unique design), then writes print_list.txt specifying how many physical
copies of each finished file to order from the printer.

Quantities:
  - Non-basic cards (ancient/rare/uncommon/common): 1 copy of base + 1 of
    upgraded (used as a one-of-each "merchant store" pool).
  - Basic cards: quantity per the real in-game starting deck composition
    (see CHARACTER_BASIC_DECKS), doubled for two starter decks per
    character -- applied to both the base and upgraded file for each card,
    since both versions appear in each deck.

Star-cost cards (star_cost_cards.json) get a wider border so their extra
badge isn't clipped; everything else uses the default.

Usage:
  python3 build_print_set.py
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from postprocess_card import DEFAULT_OUTPUT_DIR, PostprocessConfig, process_card_to_file

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("build_print_set")

CARDS_DIR = Path("cards")
STAR_COST_FILE = Path("star_cost_cards.json")
PRINT_LIST_FILE = Path("print_list.txt")

DEFAULT_BORDER_PX = 30
STAR_COST_BORDER_BONUS = 25
NUM_STARTER_DECKS = 2

# Per-character basic card slug -> copies in a single real starting deck.
CHARACTER_BASIC_DECKS: dict[str, dict[str, int]] = {
    "ironclad": {"strike-ironclad": 5, "defend-ironclad": 4, "bash": 1},
    "silent": {"strike-silent": 5, "defend-silent": 5, "neutralize": 1, "survivor": 1},
    "regent": {"strike-regent": 4, "defend-regent": 4, "venerate": 1, "falling-star": 1},
    "necrobinder": {"strike-necrobinder": 4, "defend-necrobinder": 4, "bodyguard": 1, "unleash": 1},
    "defect": {"strike-defect": 4, "defend-defect": 4, "dualcast": 1, "zap": 1},
}

BASIC_DECK_QTY: dict[str, int] = {
    slug: qty
    for deck in CHARACTER_BASIC_DECKS.values()
    for slug, qty in deck.items()
}


class PrintItem(BaseModel):
    filename: str
    slug: str
    rarity: str
    variant: Literal["base", "upgraded"]
    quantity: int


def load_star_cost_slugs() -> set[str]:
    entries = json.loads(STAR_COST_FILE.read_text())
    return {e["slug"] for e in entries}


def border_for(slug: str, star_cost_slugs: set[str]) -> int:
    if slug in star_cost_slugs:
        return DEFAULT_BORDER_PX + STAR_COST_BORDER_BONUS
    return DEFAULT_BORDER_PX


def quantity_for(slug: str, rarity: str) -> int:
    if rarity != "basic":
        return 1
    per_deck = BASIC_DECK_QTY.get(slug)
    if per_deck is None:
        raise ValueError(f"basic card {slug!r} has no entry in CHARACTER_BASIC_DECKS")
    return per_deck * NUM_STARTER_DECKS


def build() -> list[PrintItem]:
    star_cost_slugs = load_star_cost_slugs()
    items: list[PrintItem] = []

    src_files = sorted(CARDS_DIR.glob("*/*.png"))
    logger.info("Processing %d source cards...", len(src_files))

    for i, src in enumerate(src_files, 1):
        rarity = src.parent.name
        is_upgraded = src.stem.endswith("-upgraded")
        slug = src.stem[: -len("-upgraded")] if is_upgraded else src.stem
        variant: Literal["base", "upgraded"] = "upgraded" if is_upgraded else "base"

        dst = DEFAULT_OUTPUT_DIR / src.name
        config = PostprocessConfig(border_px=border_for(slug, star_cost_slugs))

        if not dst.exists():
            try:
                process_card_to_file(src, dst, config)
            except Exception as e:  # noqa: BLE001 - logged, skipped from the print set
                logger.warning("  FAILED %s: %s", src, e)
                continue

        items.append(PrintItem(
            filename=dst.name, slug=slug, rarity=rarity, variant=variant,
            quantity=quantity_for(slug, rarity),
        ))

        if i % 100 == 0:
            logger.info("  ...%d/%d", i, len(src_files))

    return items


def write_print_list(items: list[PrintItem]) -> None:
    with PRINT_LIST_FILE.open("w") as f:
        for item in sorted(items, key=lambda x: x.filename):
            f.write(f"{item.filename}\t{item.quantity}\n")


def main() -> None:
    items = build()
    write_print_list(items)

    total_copies = sum(i.quantity for i in items)
    logger.info(
        "\nDone. %d unique designs in %s, %d total physical copies in %s",
        len(items), DEFAULT_OUTPUT_DIR, total_copies, PRINT_LIST_FILE,
    )


if __name__ == "__main__":
    main()
