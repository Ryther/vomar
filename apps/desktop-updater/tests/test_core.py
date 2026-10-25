import asyncio
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]


def test_signed_packages_are_checked_without_build_tools(monkeypatch):
    from vomar_updater.core.packages import inspect_package
    import subprocess
    def forbidden(*a,**k):raise AssertionError('Runtime invoked build tool')
    monkeypatch.setattr(subprocess,'run',forbidden)
    fixture=ROOT/'tools/android/test-fixtures/common-v3-synthetic'
    p=inspect_package((fixture/'one-common.zip').read_bytes(),(fixture/'public.der').read_bytes())
    assert p.schema==3 and p.model=='VIMAR30805'
    with pytest.raises(ValueError):inspect_package(p.raw[:-10],(fixture/'public.der').read_bytes())
    candidate=ROOT/'tools/android/test-fixtures/common-v3-candidate'
    with pytest.raises(ValueError):inspect_package((candidate/'qualification-candidate.zip').read_bytes(),(candidate/'public.der').read_bytes())


def test_original_store_is_immutable_and_export_is_reopened(tmp_path):
    from vomar_updater.core.storage import Store
    s=Store(tmp_path/'Spazio è')
    key=s.put(b'original','original')
    exported=tmp_path/'original.zip';s.export(key,exported)
    assert s.reopen_receipt(key,exported)
    exported.write_bytes(b'other')
    assert not s.reopen_receipt(key,exported)
    with pytest.raises(FileExistsError):s.export(key,exported)
    s.close()


def test_restart_never_restores_consent_and_uncertainty_survives(tmp_path):
    from vomar_updater.core.storage import Store
    s=Store(tmp_path);session=s.begin({'target':'synthetic','package':'a'*64,'operation':'install'})
    s.record(session,'write-intent',{'address':4096});s.close()
    s=Store(tmp_path)
    assert s.sessions()[0]['uncertain'] is True
    assert 'consent' not in str(s.sessions())
    s.close()
