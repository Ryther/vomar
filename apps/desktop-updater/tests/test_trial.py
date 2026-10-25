from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]

def test_candidate_never_enters_normal_release_admission():
    from vomar_updater.core.packages import inspect_candidate,inspect_package
    p=ROOT/'tools/android/test-fixtures/common-v3-candidate';raw=(p/'qualification-candidate.zip').read_bytes();key=(p/'public.der').read_bytes()
    candidate=inspect_candidate(raw,key);assert candidate.manifest['purpose']=='qualification-candidate'
    with pytest.raises(ValueError):inspect_package(raw,key)
