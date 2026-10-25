"""Finite typed release bindings; family and legacy digests never coerce."""
import importlib.util,json,subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
TOOL=ROOT/'tools/firmware/build_loader_contract_bindings.py'

def run(tmp_path,records):
 source=tmp_path/'records.json';source.write_text(json.dumps(records));out=tmp_path/'bindings.h'
 return subprocess.run(['python3',str(TOOL),'--records',str(source),'--output',str(out)],capture_output=True,text=True),out

def test_finite_typed_header_compiles_with_exact_distinct_kinds(tmp_path):
 records=[dict(kind='common-code44k-anchor-v1',sha256='01'*32),dict(kind='legacy-full48k-sha256',sha256='01'*32)]
 rc,out=run(tmp_path,records);assert rc.returncode==0,rc.stderr
 source=tmp_path/'probe.c';source.write_text('#include "bindings.h"\n#include <assert.h>\nint main(void){assert(VIMAR_LOADER_CONTRACT_COUNT==2);assert(vimar_loader_contracts[0].kind==LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1);assert(vimar_loader_contracts[1].kind==LOADER_CONTRACT_LEGACY_FULL48K_SHA256);assert(vimar_loader_contracts[0].digest[0]==1);}\n')
 subprocess.run(['cc','-std=c11','-Wall','-Werror','-I'+str(tmp_path),'-I'+str(ROOT/'firmware/loader_contract'),str(source),'-o',str(tmp_path/'probe')],check=True)
 subprocess.run([str(tmp_path/'probe')],check=True)
 assert subprocess.run(['python3',str(TOOL),'--records',str(tmp_path/'records.json'),'--output',str(out)],capture_output=True).returncode!=0

@pytest.mark.parametrize('records',[[],[dict(kind='unknown',sha256='00'*32)],[dict(kind='common-code44k-anchor-v1',sha256='AA'*32)],[dict(kind='common-code44k-anchor-v1',sha256='00'*32,mask=0xb000)],[dict(kind='common-code44k-anchor-v1',sha256='00'*32)]*2,[dict(kind='legacy-full48k-sha256',sha256='00'*32),dict(kind='common-code44k-anchor-v1',sha256='00'*32)]])
def test_invalid_or_unsorted_authority_never_produces_header(tmp_path,records):
 rc,out=run(tmp_path,records);assert rc.returncode!=0 and not out.exists()


def test_duplicate_json_authority_fields_are_rejected(tmp_path):
 source=tmp_path/'records.json';source.write_text('[{"kind":"legacy-full48k-sha256","kind":"common-code44k-anchor-v1","sha256":"'+'00'*32+'"}]')
 out=tmp_path/'bindings.h';result=subprocess.run(['python3',str(TOOL),'--records',str(source),'--output',str(out)],capture_output=True)
 assert result.returncode!=0 and not out.exists()
