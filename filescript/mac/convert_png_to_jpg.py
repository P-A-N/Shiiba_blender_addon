#!/usr/bin/env python3
"""Convert PNG files to JPG in the nouhin directory."""

from pathlib import Path
from PIL import Image

def convert_png_to_jpg(nouhin_dir: Path):
    png_files = list(nouhin_dir.glob("*.png"))
    print(f"Found {len(png_files)} PNG files")

    skipped = 0
    converted = 0
    for png_path in png_files:
        jpg_path = png_path.with_suffix(".jpg")

        if jpg_path.exists():
            skipped += 1
            continue

        with Image.open(png_path) as img:
            # Convert to RGB (removes alpha channel if present)
            rgb_img = img.convert("RGB")
            rgb_img.save(jpg_path, "JPEG", quality=95)

        converted += 1
        print(f"Converted: {png_path.name} -> {jpg_path.name}")

    print(f"\nDone. Converted {converted} files, skipped {skipped} existing.")

if __name__ == "__main__":
    nouhin_dir = Path(__file__).parent / "nouhin"
    convert_png_to_jpg(nouhin_dir)
