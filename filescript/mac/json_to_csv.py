#!/usr/bin/env python3
"""Read JSON files and create a CSV file with camera data."""

import json
import csv
import glob
import os
from pathlib import Path


def get_dance_name(filename: str) -> str:
    """Extract dance name from filename prefix."""
    if filename.startswith("Shibahiki"):
        return "Shibahiki"
    elif filename.startswith("Shimonju"):
        return "Shimonju"
    elif filename.startswith("Totori"):
        return "Totori"
    return ""


def format_float(value) -> str:
    """Format float without scientific notation, removing trailing zeros."""
    if isinstance(value, float):
        return f"{value:.10f}".rstrip('0').rstrip('.')
    return value


def json_to_csv(json_dir: str = ".", output_csv: str = "output.csv"):
    """
    Read all JSON files from a directory and create a single CSV file.

    Args:
        json_dir: Directory containing JSON files
        output_csv: Output CSV file path
    """
    json_files = glob.glob(os.path.join(json_dir, "*.json"))

    if not json_files:
        print(f"No JSON files found in {json_dir}")
        return

    rows = []

    for json_path in sorted(json_files):
        with open(json_path, "r") as f:
            data = json.load(f)

        json_filename = Path(json_path).stem
        png_filename = f"{json_filename}.png"
        dance_name = get_dance_name(json_filename)

        position = data.get("position", {})
        rotation = data.get("rotation", {})

        row = {
            "png_file": png_filename,
            "dance": dance_name,
            "frame": data.get("frame", ""),
            "fov": format_float(data.get("fov", "")),
            "position_x": format_float(position.get("x", "")),
            "position_y": format_float(position.get("y", "")),
            "position_z": format_float(position.get("z", "")),
            "rotation_x": format_float(rotation.get("x", "")),
            "rotation_y": format_float(rotation.get("y", "")),
            "rotation_z": format_float(rotation.get("z", "")),
            "rotation_w": format_float(rotation.get("w", "")),
        }
        rows.append(row)

    fieldnames = [
        "png_file", "dance", "frame", "fov",
        "position_x", "position_y", "position_z",
        "rotation_x", "rotation_y", "rotation_z", "rotation_w"
    ]

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Created {output_csv} with {len(rows)} rows")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert JSON files to CSV")
    parser.add_argument("--input-dir", "-i", default=".", help="Directory containing JSON files")
    parser.add_argument("--output", "-o", default="output.csv", help="Output CSV file path")

    args = parser.parse_args()
    json_to_csv(args.input_dir, args.output)
