import hashlib,io,json,zipfile
from pathlib import Path
import pytest
from vomar_updater.core.packages import inspect_package
ROOT=Path(__file__).resolve().parents[3]
CASES=json.loads((ROOT/'tests/contracts/packages.json').read_text())['cases']

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_shared_package_contract(case):
    raw=(ROOT/case['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==case['sourceSha256']
    if case['mutation']=='truncate':raw=raw[:-10]
    if case['mutation'] in ('extra-entry','duplicate-entry'):
        out=io.BytesIO(raw)
        with zipfile.ZipFile(out,'a') as z:z.writestr('extra.txt' if case['mutation']=='extra-entry' else 'manifest.json',b'{}')
        raw=out.getvalue()
    try:result=inspect_package(raw,(ROOT/case['publicKey']).read_bytes());accepted=True
    except (ValueError,KeyError):accepted=False
    assert accepted is case['accept']
    if accepted:assert result.schema==case['schema']
