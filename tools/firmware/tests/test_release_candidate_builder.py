"""Release selection must preserve real capabilities and finite wire versions."""
from pathlib import Path

import pytest

from tools.firmware import build_typed_common_candidate as builder
from tools.firmware.package_common_android_update_v3 import WATCHDOG_HANDOFF


def test_release_versions_are_ordinary_and_coherent_for_every_signed_role():
    versions = builder.candidate_versions(WATCHDOG_HANDOFF, True, release_version='1.0.0')
    assert versions == {name: '1.0.0' for name in
                        ('main', 'recovery', 'migration', 'stockRestore', 'stockBootstrap')}
    assert builder.candidate_versions(WATCHDOG_HANDOFF, True)['main'] == '0.6.3'
    assert builder.candidate_versions()['main'] == '0.6.1'


@pytest.mark.parametrize('version', [
    '1.0.0+1', '1.0.0-rc.1', '01.0.0', '1.0', '1.0.0\n',
    '256.0.0', '1.256.0', '1.0.256', '-1.0.0', '',
])
def test_invalid_or_aliasing_release_versions_fail_before_creating_output(tmp_path, version):
    output = tmp_path / 'not-created'
    with pytest.raises(ValueError, match='version'):
        builder.build(output, Path('unused-registry'), Path('unused-policy'),
                      WATCHDOG_HANDOFF, True, release_version=version)
    assert not output.exists()


@pytest.mark.parametrize('watchdog,multibond', [(None, False), (None, True), (WATCHDOG_HANDOFF, False)])
def test_release_cannot_silently_omit_watchdog_or_multibond(tmp_path, watchdog, multibond):
    output = tmp_path / 'not-created'
    with pytest.raises(ValueError, match='watchdog|multi-bond'):
        builder.build(output, Path('unused-registry'), Path('unused-policy'),
                      watchdog, multibond, release_version='1.0.0')
    assert not output.exists()


def test_diagnostic_build_identity_changes_with_source_version_and_pair():
    identity = getattr(builder, 'fault_build_identity', None)
    assert callable(identity), 'Release builder must bind its diagnostic records to build inputs'
    sources = {'src/main.c': 'a' * 64, 'VERSION': 'b' * 64}
    versions = {name: '1.0.0' for name in builder.ROLES}
    inputs = {'main.conf': b'CONFIG_VIMAR_FAULT_DIAGNOSTICS=y\n',
              'main-pair.h': b'recovery-A', 'loader-contracts.h': b'loader-A'}
    first = identity(sources, versions, inputs)
    assert isinstance(first, bytes) and len(first) == 16
    assert identity(dict(reversed(list(sources.items()))), versions, inputs) == first
    assert identity({**sources, 'src/main.c': 'c' * 64}, versions, inputs) != first
    assert identity(sources, {**versions, 'main': '1.0.1'}, inputs) != first
    for name in inputs:
        assert identity(sources, versions, {**inputs, name: inputs[name] + b'changed'}) != first
