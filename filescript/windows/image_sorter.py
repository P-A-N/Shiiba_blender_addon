#!/usr/bin/env python
"""
Image Sorter - Sort images into categories using keyboard controls.

Controls:
  o - Move to 'ok' folder
  b - Move to 'botu' folder
  m - Move to 'maybe' folder
  s - Skip to next image (newer)
  a - Go back to previous image (older)
  q/ESC - Quit
"""

import os
import shutil
import cv2
from pathlib import Path
from ctypes import windll


def get_images(directory):
    """Get list of image files sorted by modification time (oldest first)."""
    extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
    images = []

    for f in Path(directory).iterdir():
        if f.is_file() and f.suffix.lower() in extensions:
            images.append(f)

    # Sort by modification time (oldest first)
    images.sort(key=lambda x: x.stat().st_mtime)
    return images


def ensure_directories(base_dir):
    """Ensure target directories exist."""
    for name in ['ok', 'botu', 'maybe']:
        (Path(base_dir) / name).mkdir(exist_ok=True)


def main():
    base_dir = Path.cwd()
    images = get_images(base_dir)

    if not images:
        print("No images found in current directory.")
        return

    ensure_directories(base_dir)

    # Track statistics
    stats = {'ok': 0, 'botu': 0, 'maybe': 0, 'skipped': 0}

    index = 0
    window_name = "Image Sorter"

    # Get screen dimensions
    user32 = windll.user32
    screen_width = user32.GetSystemMetrics(0)
    screen_height = user32.GetSystemMetrics(1)

    # Window size: square using screen height
    win_size = screen_height

    # Create window and position it centered
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, win_size, win_size)
    win_x = (screen_width - win_size) // 2
    win_y = 0
    cv2.moveWindow(window_name, win_x, win_y)

    print(f"Found {len(images)} images. Starting sorter...")
    print("Controls: o=ok, b=botu, m=maybe, s=next, a=prev, q/ESC=quit")

    while 0 <= index < len(images):
        img_path = images[index]

        # Check if file still exists (might have been moved)
        if not img_path.exists():
            images.pop(index)
            if index >= len(images):
                index = max(0, len(images) - 1)
            continue

        # Load and display image
        img = cv2.imread(str(img_path))
        if img is None:
            print(f"Could not load: {img_path.name}")
            index += 1
            continue

        # Scale image to fit window height while preserving aspect ratio
        img_h, img_w = img.shape[:2]
        scale = win_size / img_h
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        img_scaled = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Update window title with progress
        title = f"[{index + 1}/{len(images)}] {img_path.name}"
        cv2.setWindowTitle(window_name, title)
        cv2.imshow(window_name, img_scaled)

        # Wait for key press
        key = cv2.waitKey(0) & 0xFF

        moved = False
        target_dir = None

        if key == ord('o'):
            target_dir = 'ok'
        elif key == ord('b'):
            target_dir = 'botu'
        elif key == ord('m'):
            target_dir = 'maybe'
        elif key == ord('s'):
            # Skip to next
            stats['skipped'] += 1
            index += 1
        elif key == ord('a'):
            # Go back
            index = max(0, index - 1)
        elif key == ord('q') or key == 27:  # q or ESC
            print("\nQuitting...")
            break

        # Move file if target specified
        if target_dir:
            dest = base_dir / target_dir / img_path.name
            shutil.move(str(img_path), str(dest))
            print(f"Moved {img_path.name} -> {target_dir}/")
            stats[target_dir] += 1
            images.pop(index)
            # Stay at same index (next image shifts into current position)
            if index >= len(images):
                index = max(0, len(images) - 1)

    cv2.destroyAllWindows()

    # Print summary
    print("\n--- Summary ---")
    print(f"  ok:      {stats['ok']}")
    print(f"  botu:    {stats['botu']}")
    print(f"  maybe:   {stats['maybe']}")
    print(f"  skipped: {stats['skipped']}")
    print(f"  remaining: {len(images)}")


if __name__ == "__main__":
    main()
