"""Derive the transparent Bingzi runtime sprite from the canonical source sheet."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "shared" / "assets" / "branding" / "pet_image.png"
DEFAULT_OUTPUT = ROOT / "shared" / "assets" / "pets" / "bingzi.png"

# The upper-left pose is the stable, happy Bingzi used by both clients.
CROP_BOX = (70, 95, 720, 755)


def prepare(source: Path = DEFAULT_SOURCE, output: Path = DEFAULT_OUTPUT) -> None:
    with Image.open(source) as source_image:
        if source_image.width < CROP_BOX[2] or source_image.height < CROP_BOX[3]:
            raise ValueError(f"Pet source image is smaller than crop box: {source_image.size}")
        image = source_image.convert("RGBA").crop(CROP_BOX)
    # Remove only the connected white page background; enclosed highlights stay opaque.
    for point in ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1)):
        ImageDraw.floodfill(image, point, (255, 255, 255, 0), thresh=12)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)
    if image.getchannel("A").getbbox() is None:
        raise ValueError("Derived pet sprite is fully transparent")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    prepare(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
