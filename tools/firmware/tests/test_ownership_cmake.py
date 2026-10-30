"""Exercise selected-library admission through actual synthetic CMake projects."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / 'firmware/ownership_guard.cmake'


@pytest.mark.parametrize(('case', 'accepted'), [
    ('exact_with_companion', True),
    ('explicit_precompiled_with_sources', True),
    ('undefined_target', False),
    ('missing_archive', False),
    ('different_archive', False),
    ('short_wchar_archive', False),
    ('additional_archive', False),
    ('source_mode', False),
    ('defined_sources_false_without_precompiled', False),
])
def test_selected_library_admission(tmp_path, case, accepted):
    cmake = shutil.which('cmake')
    if cmake is None:
        pytest.skip('CMake is unavailable')
    expected = (tmp_path / 'reviewed trace/libzboss.a').as_posix()
    companion = (tmp_path / 'reviewed trace/libgppb.a').as_posix()
    different = (tmp_path / 'other/libzboss.a').as_posix()
    short_wchar = (tmp_path / 'reviewed trace/libzboss-short-wchar.a').as_posix()
    selection = {
        'missing_archive': [companion],
        'different_archive': [different],
        'short_wchar_archive': [short_wchar],
        'additional_archive': [expected, different],
    }.get(case, [expected, companion])
    lines = ['cmake_minimum_required(VERSION 3.20)',
             'project(ownership_admission NONE)',
             'set(CONFIG_VIMAR_ZIGBEE_OWNERSHIP_GUARD OFF)',
             f'include("{GUARD.as_posix()}")']
    if case != 'undefined_target':
        lines += ['add_library(zboss INTERFACE)',
                  'target_link_libraries(zboss INTERFACE ' +
                  ' '.join(f'"{path}"' for path in selection) + ')']
    if case in ('source_mode', 'explicit_precompiled_with_sources'):
        lines.append('set(CONFIG_ZBOSS_SOURCES_AVAILABLE ON)')
    if case == 'defined_sources_false_without_precompiled':
        # The SDK selects sources on DEFINED, rather than truthiness, here.
        lines.append('set(CONFIG_ZBOSS_SOURCES_AVAILABLE OFF)')
    if case == 'explicit_precompiled_with_sources':
        lines.append('set(CONFIG_ZBOSS_LIBRARY_PRECOMPILED ON)')
    lines.append(f'vimar_ownership_require_selected_library(zboss "{expected}")')
    (tmp_path / 'CMakeLists.txt').write_text('\n'.join(lines) + '\n')
    result = subprocess.run([cmake, '-S', str(tmp_path), '-B', str(tmp_path / 'build')],
                            capture_output=True, text=True)
    diagnostic = result.stdout + result.stderr
    assert 'Unknown CMake command' not in diagnostic, diagnostic
    if accepted:
        assert result.returncode == 0, diagnostic
    else:
        assert result.returncode != 0, diagnostic
