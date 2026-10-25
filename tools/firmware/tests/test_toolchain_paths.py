from pathlib import Path


def test_environment_selects_external_toolchain_and_own_signing_keys(tmp_path,monkeypatch):
 from tools.firmware.toolchain_paths import toolchain_paths
 names={'sdk':'VIMAR_NCS_WORKSPACE','python':'VIMAR_BUILD_PYTHON','west':'VIMAR_WEST','private_key':'VIMAR_SIGNING_PRIVATE_KEY','public_key':'VIMAR_SIGNING_PUBLIC_KEY'}
 for key,env in names.items():monkeypatch.setenv(env,str(tmp_path/key))
 paths=toolchain_paths()
 assert all(paths[key]==tmp_path/key for key in names)
 assert paths['imgtool']==tmp_path/'sdk/bootloader/mcuboot/scripts/imgtool.py'


def test_defaults_remain_workspace_relative(monkeypatch):
 from tools.firmware.toolchain_paths import toolchain_paths
 for key in ['VIMAR_NCS_WORKSPACE','VIMAR_BUILD_PYTHON','VIMAR_WEST','VIMAR_SIGNING_PRIVATE_KEY','VIMAR_SIGNING_PUBLIC_KEY']:monkeypatch.delenv(key,raising=False)
 paths=toolchain_paths()
 root=Path(__file__).resolve().parents[3]
 assert paths['sdk']==root/'work/ncs-zigbee'
 assert paths['python']==root/'work/ncs-venv/bin/python'
 assert paths['private_key']==root/'firmware/keys/dev-private.pem'


def test_migration_builder_uses_external_sdk_and_signing_configuration(tmp_path, monkeypatch):
 import importlib.util
 names={'SDK':'VIMAR_NCS_WORKSPACE','WEST':'VIMAR_WEST','PRIVATE_KEY':'VIMAR_SIGNING_PRIVATE_KEY','PUBLIC_KEY':'VIMAR_SIGNING_PUBLIC_KEY'}
 for key,env in names.items():monkeypatch.setenv(env,str(tmp_path/key))
 source=Path(__file__).resolve().parents[1]/'build_ota_migration.py'
 spec=importlib.util.spec_from_file_location('migration_configured',source)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 assert all(getattr(module,key)==tmp_path/key for key in names)
