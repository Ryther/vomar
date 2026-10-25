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


def test_constructed_or_replaced_package_cannot_gain_engine_admission():
    from dataclasses import replace
    from vomar_updater.core.packages import inspect_package
    p=ROOT/'tools/android/test-fixtures/common-v3-synthetic';pkg=inspect_package((p/'one-common.zip').read_bytes(),(p/'public.der').read_bytes())
    with pytest.raises(ValueError):replace(pkg,raw=b'arbitrary').assert_verified()


def test_failed_publication_does_not_commit_object_reference(tmp_path,monkeypatch):
    from vomar_updater.core.storage import Store
    import vomar_updater.core.storage as storage
    store=Store(tmp_path)
    def fail(*args):raise OSError('simulated durable publication failure')
    monkeypatch.setattr(storage,'publish_new',fail)
    with pytest.raises(OSError):store.put(b'protected','original')
    assert store.db.execute('SELECT COUNT(*) FROM objects').fetchone()[0]==0
    store.close()


def test_journal_corruption_blocks_review(tmp_path):
    from vomar_updater.core.storage import Store
    s=Store(tmp_path);session=s.begin({'target':'synthetic'});s.record(session,'write-intent',{'address':0})
    with s.db:s.db.execute('UPDATE events SET detail=? WHERE session=?',('{"address":1044480}',session))
    with pytest.raises(ValueError):s.events(session)
    s.close()
