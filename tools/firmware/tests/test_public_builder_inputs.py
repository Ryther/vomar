"""Public builder configuration must survive a source-only checkout."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

from tools.firmware import build_typed_common_candidate as builder
from tools.firmware.validate_recovery import read_config

ROOT = Path(__file__).resolve().parents[3]


def test_recovery_config_is_generated_with_only_public_source(tmp_path):
    # Removing the public config or reading experiments again breaks this test.
    snapshot = tmp_path / 'source' / 'firmware'
    shutil.copytree(ROOT / 'firmware/recovery', snapshot / 'recovery')
    destination = tmp_path / 'recovery.conf'
    builder.write_recovery_config(snapshot, destination)
    values = read_config(destination)
    assert values['CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC'] == 'y'
    assert values['CONFIG_VIMAR_RECOVERY_BOOT_HISTORY'] == 'y'
    assert values['CONFIG_VIMAR_P031_PROTECTION'] == 'y'
    assert values['CONFIG_VIMAR_LOADER_RUNTIME_V2'] == 'y'
    assert values['CONFIG_MAIN_STACK_SIZE'] == '12288'
    assert values['CONFIG_MCUMGR_TRANSPORT_WORKQUEUE_STACK_SIZE'] == '8192'
    assert values['CONFIG_MCUBOOT_SIGNATURE_KEY_FILE'] == '""'
    assert hashlib.sha256((snapshot / 'recovery/migration-exec.conf').read_bytes()).hexdigest() == 'd74ec71923bf243fa5c90425ea0d5247aa11eb7ad337d424344ba20e88f4a8fb'


def test_legacy_bridge_cli_requires_explicit_current_main_before_reading_any_input(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'tools/firmware/build_legacy_zigbee_bridge.py'),
        '--output', str(tmp_path / 'output'), '--candidate-manifest', str(tmp_path / 'missing'),
        '--legacy-recovery', str(tmp_path / 'missing-recovery')], capture_output=True, text=True)
    assert result.returncode == 2
    assert '--current-main' in result.stderr
    assert not (tmp_path / 'output').exists()
