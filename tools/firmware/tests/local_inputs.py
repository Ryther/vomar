"""Explicit optional integration inputs; ordinary source/unit failures stay failures."""
from pathlib import Path

import pytest


def local_input(path):
    """Skip only the test consuming a missing local artifact or SDK component."""
    path = Path(path)
    if not path.exists():
        pytest.skip(f'Optional local integration input unavailable: {path}')
    return path


def sdk_root():
    """Use the same external SDK override as the public build helpers."""
    from tools.firmware.toolchain_paths import toolchain_paths
    return toolchain_paths()['sdk']
