#!/usr/bin/env python3
import argparse
import csv
import hashlib
import io
import json
import struct
from pathlib import Path


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError(f"not a JPEG: {path}")
    offset = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        length = struct.unpack(">H", data[offset:offset + 2])[0]
        if marker in sof:
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            return width, height
        offset += length
    raise ValueError(f"JPEG dimensions not found: {path}")


def render(repo: Path, output: Path) -> None:
    photos = sorted(path for path in (repo / "inputs/photos").iterdir() if path.is_file())
    observations_path = repo / "analysis/hardware/photo-observations.json"
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    names = [path.name for path in photos]
    if sorted(observations) != names:
        raise ValueError("photo observation keys do not exactly match input filenames")
    rows = []
    for path in photos:
        width, height = jpeg_dimensions(path)
        record = observations[path.name]
        rows.append({
            "path": path.relative_to(repo).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": str(path.stat().st_size),
            "width": str(width),
            "height": str(height),
            "observations": "; ".join(record["observations"]),
            "limitations": "; ".join(record["limitations"]),
        })
    output.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline="")
    fields = ["path", "sha256", "bytes", "width", "height", "observations", "limitations"]
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    (output / "photo-inventory.tsv").write_text(stream.getvalue(), encoding="utf-8")

    lines = [
        "# Photo Evidence Inventory", "",
        "All source photographs remain immutable under `inputs/photos/`. Hashes and dimensions are",
        "**CONFIRMED** file properties. Text and objects listed below are literal visual observations;",
        "they do not establish nets, pin functions, voltage levels, or isolation.", "",
    ]
    for row in rows:
        lines += [
            f"## `{row['path']}`", "",
            f"- SHA-256: `{row['sha256']}`",
            f"- File: {row['bytes']} bytes, {row['width']} x {row['height']} pixels",
            f"- Visible: {row['observations']}",
            f"- Limits: {row['limitations']}", "",
        ]
    (output / "photo-inventory.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    render(args.repo.resolve(), args.output or args.repo / "analysis/hardware")


if __name__ == "__main__":
    main()
