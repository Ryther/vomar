import pytest
from tools.release.security_gate import check

def fetcher(revisions,issues=0,gate='OK'):
    def fetch(path,params):
        if 'analyses' in path:return {'analyses':[{'revision':revisions.pop(0) if len(revisions)>1 else revisions[0]}]}
        if 'project_status' in path:return {'projectStatus':{'status':gate}}
        return {'paging':{'total':issues}}
    return fetch

def test_security_gate_rechecks_exact_revision():
    sha='a'*40
    assert check(fetcher([sha]),sha,'test')
    for f in [fetcher(['b'*40]),fetcher([sha,'b'*40]),fetcher([sha],issues=1),fetcher([sha],gate='ERROR')]:
        with pytest.raises(ValueError):check(f,sha,'test')
