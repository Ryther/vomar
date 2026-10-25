"""Portable strict OTA-container and signed-primary extent parsing."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def test_ota_format(tmp_path):
    binary = tmp_path / 'ota_format'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-I', str(ROOT / 'firmware/ota'),
                    str(ROOT / 'tools/firmware/tests/ota_format_test.c'),
                    str(ROOT / 'firmware/ota/ota_format.c'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
