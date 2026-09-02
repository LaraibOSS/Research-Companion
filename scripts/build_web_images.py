#!/usr/bin/env python3
"""Generate the web-sized screenshot set the GitHub Pages site serves.

``docs/images/*.png`` are captured at 2x (2880px wide) so they stay crisp in
the README on a high-DPI display. Serving those same files from the Pages site
costs 4.5 MB across eleven figures, which is a slow first load for a page whose
whole job is a first impression.

Re-encoding at 1600px as JPEG costs 1.85 MB instead. PNG is not an option here:
resampling introduces enough colours that a 1600px PNG comes out *larger* than
the 2880px original.

The two sets are kept in sync by re-running this script, so recapturing a
screenshot never leaves the site showing a stale one::

    python scripts/build_web_images.py

The logo keeps its transparency and is copied as PNG.
"""
from __future__ import annotations

import pathlib
import shutil
import sys

WIDTH = 1600
QUALITY = 88

SRC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "images"
OUT = SRC / "web"


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is required: pip install Pillow", file=sys.stderr)
        return 1

    if not SRC.is_dir():
        print(f"no such directory: {SRC}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for png in sorted(SRC.glob("*.png")):
        if png.stem == "logo":
            # Transparency matters on a dark ground; leave it a PNG.
            dst = OUT / "logo.png"
            shutil.copyfile(png, dst)
        else:
            im = Image.open(png).convert("RGB")
            im.thumbnail((WIDTH, WIDTH), Image.LANCZOS)
            dst = OUT / f"{png.stem}.jpg"
            im.save(dst, "JPEG", quality=QUALITY, optimize=True, progressive=True)
        size = dst.stat().st_size
        total += size
        print(f"  {dst.name:18} {size / 1024:6.0f} KB")

    print(f"\n  {total / 1024 / 1024:.2f} MB in {OUT.relative_to(SRC.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
