import json
from pathlib import Path
import pytest
from tools.release.manifest import validate
ROOT=Path(__file__).resolve().parents[3]
CASES=json.loads((ROOT/'tests/contracts/distribution.json').read_text())['cases']
@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_shared_distribution_contract(case):
    if case['accept']:validate(case['manifest'])
    else:
        with pytest.raises(ValueError):validate(case['manifest'])
