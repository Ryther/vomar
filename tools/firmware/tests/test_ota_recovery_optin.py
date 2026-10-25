"""Configure actual recovery CMake both ways without invoking the SDK/compiler."""
from pathlib import Path
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('enabled', [False, True])
def test_recovery_installer_source_optin(tmp_path, enabled):
    package = tmp_path / 'zephyr'
    package.mkdir()
    (package / 'ZephyrConfig.cmake').write_text('add_library(app STATIC "${CMAKE_CURRENT_LIST_DIR}/empty.c")\n')
    (package / 'empty.c').write_text('int placeholder;\n')
    (tmp_path / 'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.20)
project(recovery_optin C)
add_subdirectory("{ROOT / 'firmware/recovery'}" recovery)
get_target_property(sources app SOURCES)
get_target_property(includes app INCLUDE_DIRECTORIES)
file(WRITE "${{CMAKE_BINARY_DIR}}/sources.txt" "${{sources}}")
file(WRITE "${{CMAKE_BINARY_DIR}}/includes.txt" "${{includes}}")
''')
    build = tmp_path / 'build'
    subprocess.run(['cmake', '-S', str(tmp_path), '-B', str(build),
                    f'-DZephyr_DIR={package}', f'-DCONFIG_VIMAR_OTA_INSTALLER={"ON" if enabled else "OFF"}'],
                   check=True, capture_output=True, text=True)
    sources = (build / 'sources.txt').read_text()
    includes = (build / 'includes.txt').read_text()
    assert 'main.c' in sources
    for name in ['ota_install.c', 'ota_image.c', 'ota_format.c', 'ota_transaction.c', 'ota_storage.c']:
        assert (name in sources) is enabled
    assert ('../ota' in includes) is enabled
