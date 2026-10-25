"""Local build configuration; no credentials, firmware or hardware access."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def toolchain_paths():
    def configured(name, default):
        # Preserve virtualenv executable symlinks: resolving them loses the venv.
        return Path(os.path.abspath(Path(os.environ.get(name) or default).expanduser()))

    paths = {
        'sdk': configured('VIMAR_NCS_WORKSPACE', ROOT / 'work/ncs-zigbee'),
        'python': configured('VIMAR_BUILD_PYTHON', ROOT / 'work/ncs-venv/bin/python'),
        'west': configured('VIMAR_WEST', ROOT / 'work/ncs-venv/bin/west'),
        'private_key': configured('VIMAR_SIGNING_PRIVATE_KEY', ROOT / 'firmware/keys/dev-private.pem'),
        'public_key': configured('VIMAR_SIGNING_PUBLIC_KEY', ROOT / 'firmware/keys/dev-public.pem'),
    }
    paths['imgtool'] = paths['sdk'] / 'bootloader/mcuboot/scripts/imgtool.py'
    return paths
