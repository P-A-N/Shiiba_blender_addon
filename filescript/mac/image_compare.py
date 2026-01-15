#!/usr/bin/env python3
"""
Image comparison tool that displays PNG images side by side from two directories.
- Left arrow: Move left image to nouhin directory, show next
- Right arrow: Move right image to nouhin directory, show next
- Q or ESC: Quit
"""

import os
import sys
import shutil
import argparse
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    print("Please install required packages: pip install opencv-python numpy")
    sys.exit(1)


def get_png_files(directory):
    """Get list of PNG files in directory."""
    return sorted([f.name for f in Path(directory).glob("*.png")])


def find_matching_pairs(left_dir, right_dir, nouhin_dir):
    """Find PNG files that exist in both directories, excluding those already in nouhin."""
    left_files = set(get_png_files(left_dir))
    right_files = set(get_png_files(right_dir))
    nouhin_files = set(get_png_files(nouhin_dir)) if nouhin_dir.exists() else set()
    matching = sorted((left_files & right_files) - nouhin_files)
    return matching


def load_and_resize_image(image_path, target_height):
    """Load image and resize to target height while maintaining aspect ratio."""
    img = cv2.imread(str(image_path))
    if img is None:
        return None

    h, w = img.shape[:2]
    scale = target_height / h
    new_w = int(w * scale)
    resized = cv2.resize(img, (new_w, target_height))
    return resized


def create_side_by_side(left_img, right_img, target_height=800):
    """Create side by side comparison image."""
    if left_img is None and right_img is None:
        return None

    # Handle missing images
    if left_img is None:
        left_img = np.zeros((target_height, 400, 3), dtype=np.uint8)
        cv2.putText(left_img, "NOT FOUND", (100, target_height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

    if right_img is None:
        right_img = np.zeros((target_height, 400, 3), dtype=np.uint8)
        cv2.putText(right_img, "NOT FOUND", (100, target_height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

    # Ensure same height
    h1, h2 = left_img.shape[0], right_img.shape[0]
    if h1 != h2:
        target_h = max(h1, h2)
        if h1 < target_h:
            left_img = cv2.resize(left_img, (int(left_img.shape[1] * target_h / h1), target_h))
        if h2 < target_h:
            right_img = cv2.resize(right_img, (int(right_img.shape[1] * target_h / h2), target_h))

    # Add separator line
    separator = np.ones((left_img.shape[0], 5, 3), dtype=np.uint8) * 128

    # Concatenate horizontally
    combined = np.hstack([left_img, separator, right_img])
    return combined


def main():
    parser = argparse.ArgumentParser(description="Compare PNG images from two directories side by side")
    parser.add_argument("left_dir", help="Left directory containing PNG images")
    parser.add_argument("right_dir", help="Right directory containing PNG images")
    parser.add_argument("--nouhin", default="nouhin", help="Output directory for selected images (default: nouhin)")
    parser.add_argument("--height", type=int, default=800, help="Display height in pixels (default: 800)")
    args = parser.parse_args()

    left_dir = Path(args.left_dir)
    right_dir = Path(args.right_dir)
    nouhin_dir = Path(args.nouhin)

    # Validate directories
    if not left_dir.is_dir():
        print(f"Error: Left directory does not exist: {left_dir}")
        sys.exit(1)
    if not right_dir.is_dir():
        print(f"Error: Right directory does not exist: {right_dir}")
        sys.exit(1)

    # Create nouhin directory if it doesn't exist
    nouhin_dir.mkdir(parents=True, exist_ok=True)

    # Find matching PNG files (excluding those already in nouhin)
    matching_files = find_matching_pairs(left_dir, right_dir, nouhin_dir)

    if not matching_files:
        print("No matching PNG files found in both directories.")
        sys.exit(1)

    print(f"Found {len(matching_files)} matching PNG files")
    print("\nControls:")
    print("  Left Arrow  - Move LEFT image to nouhin directory, show next")
    print("  Right Arrow - Move RIGHT image to nouhin directory, show next")
    print("  Q / ESC     - Quit")
    print()

    current_index = 0
    window_name = "Image Compare (Left/Right arrow to select, Q to quit)"

    while current_index < len(matching_files):
        filename = matching_files[current_index]
        left_path = left_dir / filename
        right_path = right_dir / filename

        # Load images
        left_img = load_and_resize_image(left_path, args.height)
        right_img = load_and_resize_image(right_path, args.height)

        # Create comparison view
        combined = create_side_by_side(left_img, right_img, args.height)

        # Add labels
        label_height = 50
        label_bar = np.zeros((label_height, combined.shape[1], 3), dtype=np.uint8)

        # Add LEFT/RIGHT labels
        if left_img is not None:
            left_width = left_img.shape[1]
        else:
            left_width = combined.shape[1] // 2

        cv2.putText(label_bar, "LEFT (<- to select)", (10, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(label_bar, "RIGHT (-> to select)", (left_width + 20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        # Create info bar at bottom
        info_bar = np.zeros((40, combined.shape[1], 3), dtype=np.uint8)
        info_text = f"[{current_index + 1}/{len(matching_files)}] {filename}"
        cv2.putText(info_bar, info_text, (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

        # Stack vertically
        display = np.vstack([label_bar, combined, info_bar])

        cv2.imshow(window_name, display)

        key = cv2.waitKey(0) & 0xFF

        # Left arrow key
        if key == 81 or key == 2 or key == 63234:  # Left arrow (varies by system)
            dest = nouhin_dir / filename
            shutil.move(str(left_path), str(dest))
            print(f"Moved LEFT image to nouhin: {filename}")
            current_index += 1

        # Right arrow key
        elif key == 83 or key == 3 or key == 63235:  # Right arrow (varies by system)
            dest = nouhin_dir / filename
            shutil.move(str(right_path), str(dest))
            print(f"Moved RIGHT image to nouhin: {filename}")
            current_index += 1

        # Quit
        elif key == ord('q') or key == ord('Q') or key == 27:  # Q or ESC
            print("Exiting...")
            break

    cv2.destroyAllWindows()

    if current_index >= len(matching_files):
        print("\nAll images processed!")
    print(f"Selected images are in: {nouhin_dir.absolute()}")


if __name__ == "__main__":
    main()
