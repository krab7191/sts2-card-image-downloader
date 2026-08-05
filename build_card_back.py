"""
Card Back Builder

Generates a single card-back design (same canvas size and rounded-corner
black frame as the fronts in finished_cards/) with a QR code linking to
the cosplay site, for printing as the shared back of every card.

Usage:
  python3 build_card_back.py
  python3 build_card_back.py --url https://sts2.karstenrabe.dev -o card_back.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field, HttpUrl

from postprocess_card import PostprocessConfig

_DEFAULTS = PostprocessConfig()


class CardBackConfig(BaseModel):
    url: HttpUrl = HttpUrl("https://sts2.karstenrabe.dev")
    output_size: tuple[int, int] = _DEFAULTS.output_size
    corner_radius_px: int = _DEFAULTS.corner_radius_px
    background: tuple[int, int, int, int] = (0, 0, 0, 255)
    qr_plate_color: tuple[int, int, int, int] = (245, 245, 245, 255)
    qr_plate_size_ratio: float = 0.66
    qr_plate_radius_px: int = 16
    caption: str = "sts2.karstenrabe.dev"
    caption_color: tuple[int, int, int, int] = (232, 233, 237, 255)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] - 1)], radius=radius, fill=255
    )
    return mask


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def build_card_back(config: CardBackConfig) -> Image.Image:
    out_w, out_h = config.output_size
    canvas = Image.new("RGBA", (out_w, out_h), config.background)

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        border=1,
    )
    qr.add_data(str(config.url))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color=config.qr_plate_color).convert("RGBA")

    plate_size = round(out_w * config.qr_plate_size_ratio)
    plate = Image.new("RGBA", (plate_size, plate_size), config.qr_plate_color)
    plate.putalpha(_rounded_mask((plate_size, plate_size), config.qr_plate_radius_px))

    qr_img = qr_img.resize((plate_size, plate_size), Image.NEAREST)
    plate.paste(qr_img, (0, 0), qr_img)

    plate_x = (out_w - plate_size) // 2
    plate_y = round(out_h * 0.5 - plate_size / 2 - out_h * 0.03)
    canvas.paste(plate, (plate_x, plate_y), plate)

    draw = ImageDraw.Draw(canvas)
    font = _load_font(round(out_h * 0.028))
    text_y = plate_y + plate_size + round(out_h * 0.035)
    bbox = draw.textbbox((0, 0), config.caption, font=font)
    text_x = (out_w - (bbox[2] - bbox[0])) // 2
    draw.text((text_x, text_y), config.caption, font=font, fill=config.caption_color)

    canvas.putalpha(_rounded_mask((out_w, out_h), config.corner_radius_px))
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", type=str, default=str(CardBackConfig.model_fields["url"].default))
    parser.add_argument("-o", "--output", type=Path, default=Path("card_back.png"))
    args = parser.parse_args()

    config = CardBackConfig(url=args.url)
    img = build_card_back(config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
