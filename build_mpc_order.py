"""
MPC Order Builder

Generates a single mpc-autofill order XML from finished_cards/ + print_list.txt
(produced by build_print_set.py), using absolute local file paths so the
desktop-tool never needs Google Drive credentials. Every slot not covered
by a front gets the same QR-code card back.

A single combined XML (rather than several) deliberately avoids
mpc-autofill's interactive project-splitting prompt: it only triggers when
more than one order file is loaded at once
(see aggregate_and_split_orders() in its src/order.py).

Usage:
  python3 build_mpc_order.py
  python3 build_mpc_order.py -o ../mpc-autofill/desktop-tool/order.xml
"""
from __future__ import annotations

import argparse
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from pydantic import BaseModel, Field

PRINT_LIST_PATH = Path("print_list.txt")
FINISHED_CARDS_DIR = Path("finished_cards").resolve()
CARD_BACK_PATH = Path("card_back.png").resolve()
STOCK = "(S30) Standard Smooth"


class OrderEntry(BaseModel):
    filename: str
    quantity: int = Field(gt=0)

    @property
    def path(self) -> Path:
        return FINISHED_CARDS_DIR / self.filename


def load_print_list() -> list[OrderEntry]:
    entries = []
    for line in PRINT_LIST_PATH.read_text().splitlines():
        filename, qty = line.split("\t")
        entries.append(OrderEntry(filename=filename, quantity=int(qty)))
    return entries


def build_order_xml(entries: list[OrderEntry]) -> Element:
    missing = [e.filename for e in entries if not e.path.is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} finished card(s) missing, e.g. {missing[:5]}")
    if not CARD_BACK_PATH.is_file():
        raise FileNotFoundError(f"Card back not found: {CARD_BACK_PATH}")

    total = sum(e.quantity for e in entries)

    order = Element("order")
    details = SubElement(order, "details")
    SubElement(details, "quantity").text = str(total)
    SubElement(details, "stock").text = STOCK
    SubElement(details, "foil").text = "false"

    fronts = SubElement(order, "fronts")
    slot = 0
    for entry in entries:
        card = SubElement(fronts, "card")
        SubElement(card, "id").text = str(entry.path)
        SubElement(card, "slots").text = ",".join(str(s) for s in range(slot, slot + entry.quantity))
        SubElement(card, "name").text = entry.filename
        slot += entry.quantity

    SubElement(order, "cardback").text = str(CARD_BACK_PATH)
    return order


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--output", type=Path, default=Path("mpc_order.xml"))
    args = parser.parse_args()

    entries = load_print_list()
    order = build_order_xml(entries)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(order).write(args.output, encoding="utf-8", xml_declaration=True)

    total = sum(e.quantity for e in entries)
    print(f"Saved: {args.output}")
    print(f"{len(entries)} unique designs, {total} total physical cards")


if __name__ == "__main__":
    main()
