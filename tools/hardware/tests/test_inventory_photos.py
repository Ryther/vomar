import csv
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools/hardware/inventory_photos.py"
PHOTOS = REPO / "inputs/photos"
OBSERVATIONS = REPO / "analysis/hardware/photo-observations.json"


@unittest.skipUnless(PHOTOS.is_dir() and OBSERVATIONS.is_file(),
                     'Optional local photo inputs and observations are unavailable')
class PhotoInventoryTests(unittest.TestCase):
    def test_generated_inventory_covers_sources_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for output in (first, second):
                subprocess.run(
                    ["python3", str(SCRIPT), "--repo", str(REPO), "--output", output],
                    check=True,
                )
            for name in ("photo-inventory.tsv", "photo-inventory.md"):
                self.assertEqual((Path(first) / name).read_bytes(), (Path(second) / name).read_bytes())

            with (Path(first) / "photo-inventory.tsv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            expected = sorted(f"inputs/photos/{path.name}" for path in PHOTOS.iterdir() if path.is_file())
            self.assertEqual([row["path"] for row in rows], expected)
            for row in rows:
                source = REPO / row["path"]
                self.assertEqual(row["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(int(row["bytes"]), source.stat().st_size)
                self.assertGreater(int(row["width"]), 0)
                self.assertGreater(int(row["height"]), 0)
                self.assertNotIn(str(REPO), "\t".join(row.values()))

    def test_observations_have_exact_source_keys_and_explicit_limitations(self):
        data = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        expected = sorted(path.name for path in PHOTOS.iterdir() if path.is_file())
        self.assertEqual(sorted(data), expected)
        for filename, record in data.items():
            self.assertIsInstance(record["observations"], list, filename)
            self.assertTrue(record["observations"], filename)
            self.assertIsInstance(record["limitations"], list, filename)
            self.assertTrue(record["limitations"], filename)
            self.assertNotRegex(" ".join(record["observations"]), r"\b(SDA|SCL|SWDIO|SWCLK)\b")


if __name__ == "__main__":
    unittest.main()
