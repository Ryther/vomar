"""Exercise the portable staging contract with actual bounded memory IO."""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_ota_stage(tmp_path):
    binary = tmp_path / 'ota_stage_test'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-I', str(ROOT / 'firmware/ota'),
                    str(ROOT / 'tools/firmware/tests/ota_stage_test.c'),
                    str(ROOT / 'firmware/ota/ota_stage.c'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
