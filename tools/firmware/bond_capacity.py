"""Validate resolved configurations for images that persist Bluetooth bonds."""


def validate_bond_capacity(config: dict[str, str]) -> None:
    """Require eight or more stored bonds, one active link, and authenticated access.

    Pass values from the resolved Zephyr .config, with unset symbols absent.
    Call only for images intended to persist Bluetooth bonds: Bluetooth-free
    Zigbee images and the isolated, ephemeral stock-restoration images are
    outside this policy. Disabled persistence is an error, never a silent skip.
    This validates configuration; it cannot prove runtime key preservation.
    """
    required = (
        "CONFIG_BT", "CONFIG_BT_SMP", "CONFIG_BT_SETTINGS", "CONFIG_SETTINGS",
        "CONFIG_SETTINGS_NVS", "CONFIG_NVS",
    )
    for key in required:
        if config.get(key) != "y":
            raise ValueError(f"persistent Bluetooth image requires {key}=y")

    for key, minimum, maximum in (
        ("CONFIG_BT_MAX_PAIRED", 8, None),
        ("CONFIG_BT_MAX_CONN", 1, 1),
    ):
        try:
            value = int(config.get(key, ""))
        except ValueError:
            raise ValueError(f"persistent Bluetooth image requires resolved {key}") from None
        if value < minimum or (maximum is not None and value > maximum):
            bound = f"at least {minimum}" if maximum is None else str(minimum)
            raise ValueError(f"persistent Bluetooth image requires {key}={bound}")

    if config.get("CONFIG_BT_KEYS_OVERWRITE_OLDEST", "n") != "n":
        raise ValueError("CONFIG_BT_KEYS_OVERWRITE_OLDEST must be disabled to preserve existing bonds")
    if (config.get("CONFIG_MCUMGR_TRANSPORT_BT") == "y"
            and config.get("CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN") != "y"):
        raise ValueError("Bluetooth MCUmgr requires CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN=y")
