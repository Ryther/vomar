"""Reject resolved persistent-Bluetooth images that could lose existing bonds."""
import pytest

from tools.firmware.bond_capacity import validate_bond_capacity


@pytest.fixture
def recovery_config():
    # Representative resolved .config values, as returned by read_config().
    return {
        "CONFIG_BT": "y",
        "CONFIG_BT_SMP": "y",
        "CONFIG_BT_SETTINGS": "y",
        "CONFIG_SETTINGS": "y",
        "CONFIG_SETTINGS_NVS": "y",
        "CONFIG_NVS": "y",
        "CONFIG_BT_MAX_PAIRED": "8",
        "CONFIG_BT_MAX_CONN": "1",
        "CONFIG_MCUMGR_TRANSPORT_BT": "y",
        "CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN": "y",
    }


def test_accepts_eight_bonds_single_link_and_implicit_no_eviction(recovery_config):
    assert validate_bond_capacity(recovery_config) is None


def test_accepts_explicit_no_eviction_and_additional_key_capacity(recovery_config):
    recovery_config.update(CONFIG_BT_KEYS_OVERWRITE_OLDEST="n", CONFIG_BT_MAX_PAIRED="16")
    assert validate_bond_capacity(recovery_config) is None


@pytest.mark.parametrize("value", [None, "0", "1", "7", "invalid"])
def test_rejects_insufficient_or_unknown_stored_bond_capacity(recovery_config, value):
    if value is None:
        del recovery_config["CONFIG_BT_MAX_PAIRED"]
    else:
        recovery_config["CONFIG_BT_MAX_PAIRED"] = value
    with pytest.raises(ValueError, match="BT_MAX_PAIRED"):
        validate_bond_capacity(recovery_config)


@pytest.mark.parametrize("value", [None, "0", "2", "8", "invalid"])
def test_rejects_anything_except_one_active_connection(recovery_config, value):
    if value is None:
        del recovery_config["CONFIG_BT_MAX_CONN"]
    else:
        recovery_config["CONFIG_BT_MAX_CONN"] = value
    with pytest.raises(ValueError, match="BT_MAX_CONN"):
        validate_bond_capacity(recovery_config)


def test_rejects_oldest_bond_eviction(recovery_config):
    recovery_config["CONFIG_BT_KEYS_OVERWRITE_OLDEST"] = "y"
    with pytest.raises(ValueError, match="BT_KEYS_OVERWRITE_OLDEST"):
        validate_bond_capacity(recovery_config)


@pytest.mark.parametrize("key", [
    "CONFIG_BT", "CONFIG_BT_SMP", "CONFIG_BT_SETTINGS", "CONFIG_SETTINGS",
    "CONFIG_SETTINGS_NVS", "CONFIG_NVS",
])
@pytest.mark.parametrize("value", [None, "n"])
def test_rejects_disabled_bluetooth_authentication_or_persistence(recovery_config, key, value):
    if value is None:
        del recovery_config[key]
    else:
        recovery_config[key] = value
    with pytest.raises(ValueError, match=key):
        validate_bond_capacity(recovery_config)


@pytest.mark.parametrize("value", [None, "n"])
def test_rejects_smp_transport_without_authenticated_access(recovery_config, value):
    if value is None:
        del recovery_config["CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN"]
    else:
        recovery_config["CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN"] = value
    with pytest.raises(ValueError, match="MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN"):
        validate_bond_capacity(recovery_config)


def test_accepts_persistent_research_service_without_mcumgr(recovery_config):
    del recovery_config["CONFIG_MCUMGR_TRANSPORT_BT"]
    del recovery_config["CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN"]
    assert validate_bond_capacity(recovery_config) is None
