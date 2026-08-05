"""
Card Image Postprocessor

Downloaded card art sits in a large transparent canvas (the art itself
isn't a full rectangle), and some cards have badges (rarity gems, etc.)
that stick out past the card's own frame by different amounts. This
detects the card's main frame (ignoring those badges), fits it into the
standard MTG card size (750x1050 px, 2.5x3.5in @ 300dpi) without
stretching, and adds a thin black rounded-rectangle border around it
(Magic: The Gathering style) with the frame centered in that border.
Badges/decorations that stick out past the frame just ride along and can
spill into the border area (or get clipped at the edge) rather than
forcing lopsided padding to fit them in -- like alternate-art MTG cards
bleeding past their frame.

`--border` and `--radius` are exact pixel values on the final output,
not scaled from a source resolution.

Usage:
  python3 postprocess_card.py cards/ancient/abundance.png
  python3 postprocess_card.py cards/ancient/abundance.png -o preview.png
  python3 postprocess_card.py cards/ancient/abundance.png --trim-margin 2 --border 5 --radius 12
"""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

# Finished cards go in one flat folder, no rarity subdirectories -- rarity
# only matters for the raw download layout in cards/.
DEFAULT_OUTPUT_DIR = Path("finished_cards")

# Vertical/horizontal bands used to sample the card's main frame edges,
# as fractions of image size. Chosen to stay clear of corner badges
# (cost gem, rarity gems) and top-center decorations while still covering
# enough of the frame to make the median robust to any one row/column
# being contaminated by a badge or decoration.
_FRAME_ROW_BAND = (0.25, 0.85)
_FRAME_COL_BAND = (0.15, 0.85)


def _detect_frame_bbox(alpha: Image.Image, threshold: int) -> tuple[int, int, int, int]:
    """Median-based estimate of the card's main frame, ignoring badges/decorations.

    Badges (cost gem, rarity gems) and decorations (e.g. a flame above the
    title) sit in the top-left and top-center of the card and often stick
    out past the frame's own edge. Sampling many rows/columns and taking
    the median rejects those as outliers rather than letting them dominate
    a plain bounding box, without needing to hardcode where a given card's
    badges are.
    """
    w, h = alpha.size
    px = alpha.load()

    lefts: list[int] = []
    rights: list[int] = []
    for y in range(int(h * _FRAME_ROW_BAND[0]), int(h * _FRAME_ROW_BAND[1])):
        row = [x for x in range(w) if px[x, y] > threshold]
        if row:
            lefts.append(row[0])
            rights.append(row[-1])

    tops: list[int] = []
    bottoms: list[int] = []
    for x in range(int(w * _FRAME_COL_BAND[0]), int(w * _FRAME_COL_BAND[1])):
        col = [y for y in range(h) if px[x, y] > threshold]
        if col:
            tops.append(col[0])
            bottoms.append(col[-1])

    if not (lefts and rights and tops and bottoms):
        raise ValueError("could not detect a frame -- image may be blank")

    return (
        int(statistics.median(lefts)), int(statistics.median(tops)),
        int(statistics.median(rights)), int(statistics.median(bottoms)),
    )


class PostprocessConfig(BaseModel):
    trim_margin_px: int = Field(2, ge=0)
    border_px: int = Field(30, ge=0)
    corner_radius_px: int = Field(20, ge=0)
    alpha_threshold: int = Field(10, ge=0, le=255)
    output_size: tuple[int, int] = (825, 1125)


def process_card(src: Path, config: PostprocessConfig) -> Image.Image:
    img = Image.open(src).convert("RGBA")
    alpha = img.getchannel("A")

    content_mask = alpha.point(lambda p: 255 if p > config.alpha_threshold else 0)
    content_bbox = content_mask.getbbox()
    if content_bbox is None:
        raise ValueError(f"{src}: no non-transparent content found")

    frame_left, frame_top, frame_right, frame_bottom = _detect_frame_bbox(alpha, config.alpha_threshold)
    frame_w = frame_right - frame_left
    frame_h = frame_bottom - frame_top

    left, top, right, bottom = content_bbox
    left = max(left - config.trim_margin_px, 0)
    top = max(top - config.trim_margin_px, 0)
    right = min(right + config.trim_margin_px, img.width)
    bottom = min(bottom + config.trim_margin_px, img.height)
    trimmed = img.crop((left, top, right, bottom))

    out_w, out_h = config.output_size
    content_area_w = out_w - 2 * config.border_px
    content_area_h = out_h - 2 * config.border_px

    # Scale so the *frame* (not badges/decorations sticking out past it)
    # fits the content area -- keeps the frame the same relative size and
    # perfectly centered across every card, regardless of how far any one
    # badge happens to poke out. Outlier badges (e.g. the wide "Regent"
    # star cost) can end up slightly clipped rather than shifting the
    # frame off-center -- see the separate star-cost handling instead.
    scale = min(content_area_w / frame_w, content_area_h / frame_h)
    fitted = trimmed.resize(
        (round(trimmed.width * scale), round(trimmed.height * scale)), Image.LANCZOS
    )

    # Center the *frame* on the canvas, not the trimmed content as a whole.
    # Anything sticking out past the frame (badges, glow effects) rides
    # along and can spill into the border -- or get slightly clipped at
    # the canvas edge -- like alternate-art MTG cards bleeding past their
    # frame, rather than pushing the frame itself off-center to fit.
    frame_center_x = (frame_left - left + frame_w / 2) * scale
    frame_center_y = (frame_top - top + frame_h / 2) * scale
    offset = (round(out_w / 2 - frame_center_x), round(out_h / 2 - frame_center_y))

    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 255))
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
