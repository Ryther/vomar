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


RECOVERY_ABI_CONFIG={
 'CONFIG_VIMAR_OTA_INSTALLER':'y','CONFIG_VIMAR_OTA_SPLIT_STAGING':'y',
 'CONFIG_VIMAR_P031_PROTECTION':'y','CONFIG_NRF_COMPRESS_DECOMPRESSION':'y',
 'CONFIG_NRF_COMPRESS_LZMA_VERSION_LZMA2':'y','CONFIG_NRF_COMPRESS_ARM_THUMB':'y',
 'CONFIG_NRF_COMPRESS_LZMA_MAX_DICT_SIZE':'32768',
 'CONFIG_NRF_COMPRESS_LZMA_MAX_LC_LP':'3','CONFIG_NRF_COMPRESS_LZMA_LP':'0',
 'CONFIG_DISABLE_FLASH_PATCH':'n',
}

def test_release_recovery_contract_is_independent_of_semver():
 validate=getattr(builder,'validate_recovery_contract',None)
 assert callable(validate),'Profile2 signing must enforce its stable recovery ABI'
 assert validate(RECOVERY_ABI_CONFIG)=='vimar30805-split-v2'

@pytest.mark.parametrize('field',list(RECOVERY_ABI_CONFIG))
def test_recovery_cannot_reuse_profile2_with_an_incompatible_build(field):
 validate=getattr(builder,'validate_recovery_contract',None)
 assert callable(validate)
 config={**RECOVERY_ABI_CONFIG,field:'y' if field=='CONFIG_DISABLE_FLASH_PATCH' else 'unsupported'}
 with pytest.raises(ValueError,match='recovery contract'):
  validate(config)


def test_beta_public_label_keeps_numeric_image_and_wire_versions(tmp_path):
    from tools.firmware.package_zigbee_ota import ota_version
    first = builder.candidate_versions(WATCHDOG_HANDOFF, True, '1.1.7-beta1')
    second = builder.candidate_versions(WATCHDOG_HANDOFF, True, '1.1.7-beta2')
    assert set(first.values()) == {'1.1.7+1'}
    assert set(second.values()) == {'1.1.7+2'}
    assert ota_version('1.1.6') < ota_version(first['main']) < ota_version(second['main']) < ota_version('1.1.8')
    path = tmp_path/'VERSION'
    builder.version(path, first['main'], extra='beta1')
    assert 'VERSION_TWEAK = 1\nEXTRAVERSION = beta1\n' in path.read_text()


@pytest.mark.parametrize('value', ['1.1.7-beta0', '1.1.7-beta01', '1.1.7-beta255', '1.1.7-beta1\n', '1.1.7-beta.1'])
def test_beta_labels_are_bounded_and_unambiguous(value):
    with pytest.raises(ValueError, match='version'):
        builder.candidate_versions(WATCHDOG_HANDOFF, True, value)


def test_guard_requires_explicit_beta_before_creating_output(tmp_path):
    with pytest.raises(ValueError, match='beta'):
        builder.build(tmp_path/'absent', Path('unused'), Path('unused'), WATCHDOG_HANDOFF, True,
                      release_version='1.1.7', ownership_guard=True)
    assert not (tmp_path/'absent').exists()


@pytest.mark.parametrize('damage', [None, 'failed', 'stale', 'missing'])
def test_ownership_admission_binds_the_actual_elf(tmp_path, damage):
    import hashlib,json
    (tmp_path/'zephyr').mkdir();elf=tmp_path/'zephyr/zephyr.elf';elf.write_bytes(b'fixture ELF')
    report={'passed':damage!='failed','sha256':hashlib.sha256(elf.read_bytes()).hexdigest()}
    if damage=='stale':report['sha256']='0'*64
    if damage!='missing':(tmp_path/'ownership-link-audit.json').write_text(json.dumps(report))
    if damage:
        with pytest.raises(ValueError,match='ownership'):
            builder.require_ownership_main(tmp_path)
    else:
        assert builder.require_ownership_main(tmp_path)['elf_sha256']==report['sha256']
