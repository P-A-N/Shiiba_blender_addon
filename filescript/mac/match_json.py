import os
import shutil
from pathlib import Path

def main():
    current_dir = Path.cwd()
    parent_dir = current_dir.parent
    notfound_dir = current_dir / "notfound"

    # Get all PNG files in current directory
    png_files = list(current_dir.glob("*.png"))

    if not png_files:
        print("No PNG files found in current directory.")
        return

    found_count = 0
    notfound_count = 0

    for png_file in png_files:
        # Get the base name without extension
        base_name = png_file.stem
        json_filename = f"{base_name}.json"
        json_path = parent_dir / json_filename

        if json_path.exists():
            # Copy JSON file to current directory
            dest_path = current_dir / json_filename
            shutil.copy2(json_path, dest_path)
            print(f"Copied: {json_filename}")

            # Also copy PLY file if it exists
            ply_filename = f"{base_name}.ply"
            ply_path = parent_dir / ply_filename
            if ply_path.exists():
                ply_dest_path = current_dir / ply_filename
                shutil.copy2(ply_path, ply_dest_path)
                print(f"Copied: {ply_filename}")

            found_count += 1
        else:
            # Create notfound directory if it doesn't exist
            notfound_dir.mkdir(exist_ok=True)
            # Move PNG file to notfound directory
            dest_path = notfound_dir / png_file.name
            shutil.move(str(png_file), str(dest_path))
            print(f"Moved to notfound: {png_file.name}")
            notfound_count += 1

    print(f"\nSummary:")
    print(f"  JSON files copied: {found_count}")
    print(f"  PNG files moved to notfound: {notfound_count}")

if __name__ == "__main__":
    main()
