"""
Card Image Postprocessor

Downloaded card art sits in a large transparent canvas (the art itself
isn't a full rectangle). This trims that padding down to a small margin
around the actual card content, fits it into the standard MTG card size
(750x1050 px, 2.5x3.5in @ 300dpi) without stretching, and adds a thin
black rounded-rectangle border around it (Magic: The Gathering style).

The trimmed art's aspect ratio won't exactly match a real MTG card, so
rather than stretching it to fill the frame, it's scaled to fit and
centered — whichever axis has leftover space just gets a thicker border
on that side instead of distorting the art. `--border` and `--radius`
are exact pixel values on the final output, not scaled from a source
resolution.

Usage:
  python3 postprocess_card.py cards/ancient/abundance.png
  python3 postprocess_card.py cards/ancient/abundance.png -o preview.png
  python3 postprocess_card.py cards/ancient/abundance.png --trim-margin 2 --border 5 --radius 12
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

# Finished cards go in one flat folder, no rarity subdirectories -- rarity
# only matters for the raw download layout in cards/.
DEFAULT_OUTPUT_DIR = Path("finished_cards")


class PostprocessConfig(BaseModel):
    trim_margin_px: int = Field(2, ge=0)
    border_px: int = Field(5, ge=0)
    corner_radius_px: int = Field(20, ge=0)
    alpha_threshold: int = Field(10, ge=0, le=255)
    output_size: tuple[int, int] = (750, 1050)


def process_card(src: Path, config: PostprocessConfig) -> Image.Image:
    img = Image.open(src).convert("RGBA")

    alpha = img.getchannel("A")
    content_mask = alpha.point(lambda p: 255 if p > config.alpha_threshold else 0)
    bbox = content_mask.getbbox()
    if bbox is None:
        raise ValueError(f"{src}: no non-transparent content found")

    left, top, right, bottom = bbox
    left = max(left - config.trim_margin_px, 0)
    top = max(top - config.trim_margin_px, 0)
    right = min(right + config.trim_margin_px, img.width)
    bottom = min(bottom + config.trim_margin_px, img.height)
    trimmed = img.crop((left, top, right, bottom))

    out_w, out_h = config.output_size
    content_area_w = out_w - 2 * config.border_px
    content_area_h = out_h - 2 * config.border_px

    # Fit the trimmed art within the content area without stretching --
    # scale to whichever dimension is the tighter constraint.
    scale = min(content_area_w / trimmed.width, content_area_h / trimmed.height)
    fitted = trimmed.resize(
        (round(trimmed.width * scale), round(trimmed.height * scale)), Image.LANCZOS
    )

    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 255))
    offset = ((out_w - fitted.width) // 2, (out_h - fitted.height) // 2)
    canvas.paste(fitted, offset, fitted)

    corner_mask = Image.new("L", (out_w, out_h), 0)
    ImageDraw.Draw(corner_mask).rounded_rectangle(
        [(0, 0), (out_w - 1, out_h - 1)],
        radius=config.corner_radius_px,
        fill=255,
    )
    canvas.putalpha(corner_mask)
    return canvas


def process_card_to_file(src: Path, dst: Path, config: PostprocessConfig) -> Path:
    result = process_card(src, config)
    dst.parent.mkdir(parents=True, exist_ok=True)
    result.save(dst)
    return dst


def main() -> None:
    defaults = PostprocessConfig()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help=f"Defaults to {DEFAULT_OUTPUT_DIR}/<input filename>",
    )
    parser.add_argument(
        "--trim-margin", type=int, default=defaults.trim_margin_px,
        help="Padding kept around the trimmed source content, in px (source resolution)",
    )
    parser.add_argument(
        "--border", type=int, default=defaults.border_px,
        help="Black border thickness (minimum, on the tight axis), in px (output resolution)",
    )
    parser.add_argument(
        "--radius", type=int, default=defaults.corner_radius_px,
        help="Outer corner radius, in px (output resolution)",
    )
    parser.add_argument("--width", type=int, default=defaults.output_size[0], help="Output width, in px")
    parser.add_argument("--height", type=int, default=defaults.output_size[1], help="Output height, in px")
    args = parser.parse_args()

    config = PostprocessConfig(
        trim_margin_px=args.trim_margin,
        border_px=args.border,
        corner_radius_px=args.radius,
        output_size=(args.width, args.height),
    )
    output = args.output or (DEFAULT_OUTPUT_DIR / args.input.name)
    process_card_to_file(args.input, output, config)
    print(f"Saved ({config.output_size[0]}x{config.output_size[1]}): {output}")


if __name__ == "__main__":
    main()
