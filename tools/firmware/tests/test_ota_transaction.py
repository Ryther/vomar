"""Compile the portable journal contract independently from Zephyr."""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_transaction_contract(tmp_path):
    executable = tmp_path / 'transaction'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-I', str(ROOT / 'firmware/ota'),
                    str(ROOT / 'tools/firmware/tests/ota_transaction_test.c'),
                    str(ROOT / 'firmware/ota/ota_transaction.c'), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)

def test_version2_journal_binding_geometry_and_corruption(tmp_path):
    executable=tmp_path/'transaction2'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-I',str(ROOT/'firmware/ota'),str(ROOT/'tools/firmware/tests/ota_transaction_v2_test.c'),str(ROOT/'firmware/ota/ota_transaction.c'),'-o',str(executable)],check=True)
    subprocess.run([str(executable)],check=True)
