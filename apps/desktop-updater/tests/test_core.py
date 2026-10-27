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


@pytest.fixture
def versioned_signed_package(monkeypatch):
    """Reuse the pure synthetic builder with one disposable, in-memory signer."""
    import io
    import runpy
    import zipfile
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from tools.firmware.package_common_android_update_v3 import canonical, sha, strict_json
    builder=runpy.run_path(str(ROOT/'tools/android/first_install_contract/tests/test_first_install_contract.py'))['common_fixture']
    key=ec.generate_private_key(ec.SECP256R1())
    def package(minimum,*,candidate=False,invalid_signature=False):
        # Only fixture randomness is controlled; admission uses real validators.
        with monkeypatch.context() as generation:
            generation.setattr(ec,'generate_private_key',lambda curve:key)
            _,public,_,entries=builder(candidate=candidate)
        manifest=strict_json(entries['manifest.json'])
        manifest['minAppVersion']=minimum
        del manifest['bundleId']
        manifest['bundleId']=sha(canonical(manifest))
        entries['manifest.json']=canonical(manifest)
        signature=key.sign(entries['manifest.json'],ec.ECDSA(hashes.SHA256()))
        if invalid_signature:signature=signature[:-1]+bytes([signature[-1]^1])
        entries['manifest.sig']=signature
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in entries.items():archive.writestr(name,data)
        return output.getvalue(),public
    return package


@pytest.mark.parametrize('candidate',[False,True])
def test_default_admission_uses_current_native_version(versioned_signed_package,candidate):
    from vomar_updater.core.packages import inspect_candidate,inspect_package
    inspect=inspect_candidate if candidate else inspect_package
    raw,public=versioned_signed_package('1.1.0',candidate=candidate)
    package=inspect(raw,public)
    package.assert_verified()
    assert package.manifest['minAppVersion']=='1.1.0'
    with pytest.raises(ValueError,match='newer updater'):
        inspect(raw,public,app_version='1.0.0')


@pytest.mark.parametrize('candidate',[False,True])
def test_default_native_admission_rejects_newer_minimum(versioned_signed_package,candidate):
    from vomar_updater.core.packages import inspect_candidate,inspect_package
    inspect=inspect_candidate if candidate else inspect_package
    raw,public=versioned_signed_package('1.2.0',candidate=candidate)
    with pytest.raises(ValueError,match='newer updater'):
        inspect(raw,public)


@pytest.mark.parametrize('candidate',[False,True])
def test_native_version_default_preserves_signature_and_purpose_checks(versioned_signed_package,candidate):
    from vomar_updater.core.packages import inspect_candidate,inspect_package
    inspect=inspect_candidate if candidate else inspect_package
    wrong_route=inspect_package if candidate else inspect_candidate
    raw,public=versioned_signed_package('1.1.0',candidate=candidate)
    with pytest.raises(ValueError):wrong_route(raw,public)
    raw,public=versioned_signed_package('1.1.0',candidate=candidate,invalid_signature=True)
    with pytest.raises(ValueError,match='signature'):inspect(raw,public)
