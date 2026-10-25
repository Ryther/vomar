import pytest
from tools.firmware.build_typed_common_candidate import candidate_versions
from tools.firmware.package_common_android_update_v3 import WATCHDOG_HANDOFF

def test_multibond_images_have_new_semver_for_each_changed_component():
    result=candidate_versions(WATCHDOG_HANDOFF,True)
    old={'main':'0.6.2','recovery':'0.8.2','migration':'0.9.2','stockRestore':'0.10.1','stockBootstrap':'0.11.1'}
    assert set(result)==set(old)
    for role in old:
        assert tuple(map(int,result[role].split('.')))>tuple(map(int,old[role].split('.')))

def test_multibond_cannot_drop_watchdog_handoff_policy():
    with pytest.raises(ValueError,match='watchdog'):
        candidate_versions(None,True)
