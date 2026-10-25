"""Public artifact measurement helper: explicit types, exact fixed spans."""
import hashlib,importlib,json,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

@pytest.fixture
def helper():return importlib.import_module('tools.firmware.loader_runtime_contract')

def test_family_measurement_is_domain_separated_and_legacy_never_masks_anchor(helper):
 code=bytes((i*7)%256 for i in range(0xb000));one=code+b'\xff'*4096;two=code+b'\x01'*4096
 a=helper.measure_record(one,helper.COMMON_KIND);b=helper.measure_record(two,helper.COMMON_KIND)
 assert a==b and a.sha256==hashlib.sha256(b'VIMAR30805-LOADER-CODE44K-ANCHOR1\0'+code).hexdigest()
 assert helper.measure_record(one,helper.LEGACY_KIND)!=helper.measure_record(two,helper.LEGACY_KIND)
 assert helper.measure_record(one,helper.LEGACY_KIND).sha256==hashlib.sha256(one).hexdigest()
 for raw in [one[:-1],one+b'\xff']:
  with pytest.raises(ValueError):helper.measure_record(raw,helper.COMMON_KIND)
 with pytest.raises(ValueError):helper.measure_record(one,'blind-mask')

@pytest.mark.parametrize('value',[[],[{'kind':'other','sha256':'a'*64}],[{'kind':'common-code44k-anchor-v1','sha256':'A'*64}],[{'kind':'common-code44k-anchor-v1','sha256':'a'*64,'mask':[0,45056]}],[{'kind':'legacy-full48k-sha256','sha256':False}], [{'kind':'legacy-full48k-sha256','sha256':'a'*64}]*2])
def test_unknown_ambiguous_or_legacy_mixed_semantics_reject(helper,value):
 with pytest.raises(ValueError):helper.validate_records(value)

def test_canonical_typed_records_and_offline_cli(helper,tmp_path):
 raw=b'\xff'*0xc000;record=helper.measure_record(raw,helper.COMMON_KIND)
 encoded=helper.canonical_records((record,));assert encoded==json.dumps([{'kind':record.kind,'sha256':record.sha256}],sort_keys=True,separators=(',',':')).encode()+b'\n'
 assert helper.validate_records(json.loads(encoded))==(record,)
 path=tmp_path/'loader.bin';path.write_bytes(raw)
 command=[sys.executable,str(ROOT/'tools/firmware/loader_runtime_contract.py'),str(path),'--kind',helper.COMMON_KIND]
 result=subprocess.run(command,capture_output=True,check=True);assert result.stdout==encoded
 assert 'uid' not in result.stdout.decode().lower()
