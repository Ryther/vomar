"""Unsigned build proof boundaries, not an invocation of a target SDK/hardware."""
from pathlib import Path
import importlib.util
import pytest

ROOT=Path(__file__).resolve().parents[3]

@pytest.fixture
def builder():
    path=ROOT/'tools/firmware/build_common_restore_probe.py'
    assert path.exists(),'Isolated unsigned RESTORE builder is missing'
    spec=importlib.util.spec_from_file_location('restore_builder',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_generated_finite_binding_has_no_uid_anchor_or_legacy_contract(builder):
    header=builder.binding_header('a'*64)
    assert 'LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1' in header
    assert 'VIMAR_LOADER_CONTRACT_COUNT 1U' in header
    assert 'LEGACY_FULL48K' not in header and 'DEVICEID' not in header
    for invalid in ['','a'*63,'A'*64,'0x'+'a'*64]:
        with pytest.raises(ValueError):builder.binding_header(invalid)

def test_ram_call_graph_rejects_flash_callee_and_keeps_indirect_callbacks_explicit(builder):
    good='20001000 <ram_entry>:\n20001000: f000 bl 20002000 <common_restore_finalizer_core>\n20002000 <common_restore_finalizer_core>:\n20002000: 4780 blx r0\n'
    assert builder.ram_call_graph(good,{'ram_entry','common_restore_finalizer_core'})
    with pytest.raises(ValueError):builder.ram_call_graph(good.replace('20002000 <common_restore_finalizer_core>','000b2000 <common_restore_finalizer_core>'),{'ram_entry'})

def test_existing_or_immutable_output_is_refused_without_touching_it(builder,tmp_path):
    target=tmp_path/'proof';target.mkdir();(target/'old').write_bytes(b'preserve')
    with pytest.raises(ValueError):builder.validate_output(target)
    assert (target/'old').read_bytes()==b'preserve'
    with pytest.raises(ValueError):builder.validate_output(ROOT/'inputs'/'new-proof')
