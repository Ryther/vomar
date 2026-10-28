"""Synthetic Linux package provenance; never queries host packages or a network."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from tools.release import inventory
from tools.release.manifest import digest


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "_internal").mkdir(parents=True)
    system = tmp_path / "system"
    system.mkdir()
    monkeypatch.setattr(inventory, "commit", lambda: "a" * 40)
    monkeypatch.setattr(inventory.metadata, "distribution", lambda name: SimpleNamespace(
        metadata={"Name": name}, version="1.0.0", requires=[]))
    monkeypatch.setattr(inventory.metadata, "version", lambda name: "6.10.0")
    calls = []

    def fake_query(args, **kwargs):
        calls.append(args)
        assert args[0] == "dpkg-query"
        assert kwargs["timeout"] == 10
        if args[1] == "--search":
            filename = args[2].removeprefix("*/")
            source = system / filename
            return subprocess.CompletedProcess(args, 0, f"libssl3:amd64: {source}\n", "")
        assert args == ["dpkg-query", "--show", "--showformat=${binary:Package}\t${Version}\t${db:Status-Status}\n", "libssl3:amd64"]
        return subprocess.CompletedProcess(args, 0, "libssl3:amd64\t3.0.2-0ubuntu1.20\tinstalled\n", "")

    monkeypatch.setattr(inventory.subprocess, "run", fake_query)
    return bundle, system, calls, fake_query


def test_linux_inventory_binds_each_shipped_library_to_exact_vendor_package(prepared):
    bundle, system, calls, _ = prepared
    for name, payload in [("libssl.so.3", b"synthetic ssl"), ("libcrypto.so.3", b"synthetic crypto")]:
        (bundle / "_internal" / name).write_bytes(payload)
        (system / name).write_bytes(payload)
    observed = inventory.native(bundle, "linux-x64", [])
    assert observed["systemComponents"] == [
        {"path": "_internal/" + name, "sha256": digest(payload), "status": "matched",
         "packageManager": "dpkg", "package": "libssl3:amd64", "version": "3.0.2-0ubuntu1.20",
         "sourcePath": str(system / name), "sourceSha256": digest(payload), "ownedPath": str(system / name)}
        for name, payload in [("libcrypto.so.3", b"synthetic crypto"), ("libssl.so.3", b"synthetic ssl")]
    ]
    assert observed["packages"] == [
        {"ecosystem": "PyPI", "name": name, "version": "1.0.0"}
        for name in ["vomar-updater", "PySide6-Essentials", "shiboken6", "PyInstaller"]
    ]
    assert all(row["package"] not in [p["name"] for p in observed["packages"]] for row in observed["systemComponents"])
    assert calls


@pytest.mark.parametrize("damage", ["different-bytes", "missing-source", "source-is-shipped-file", "source-is-symlink"])
def test_unmatched_source_is_explicit_and_never_receives_a_package_version(prepared, monkeypatch, damage):
    bundle, system, calls, query = prepared
    shipped = bundle / "_internal/libssl.so.3"
    shipped.write_bytes(b"shipped")
    source = system / "libssl.so.3"
    if damage == "different-bytes":
        source.write_bytes(b"not shipped")
    elif damage == "source-is-shipped-file":
        def self_owned(args, **kwargs):
            assert args[1] == "--search"
            return subprocess.CompletedProcess(args, 0, f"libssl3:amd64: {shipped}\n", "")
        monkeypatch.setattr(inventory.subprocess, "run", self_owned)
    elif damage == "source-is-symlink":
        target = system / "unowned-payload"
        target.write_bytes(b"shipped")
        source.symlink_to(target)
    row = inventory.native(bundle, "linux-x64", [])["systemComponents"][0]
    assert row["status"] == "unresolved"
    assert row["path"] == "_internal/libssl.so.3"
    assert row["sha256"] == digest(b"shipped")
    assert row["reason"]
    assert "package" not in row and "version" not in row
    assert all(args[1] != "--show" for args in calls)


@pytest.mark.parametrize("answer", [None, "other-package:amd64\t3.0.2-0ubuntu1.20\tinstalled\n",
                                    "libssl3:amd64\t\tinstalled\n", "libssl3:amd64\t3.0.2-0ubuntu1.20\tconfig-files\n"])
def test_missing_or_inconsistent_package_metadata_cannot_claim_vendor_provenance(prepared, monkeypatch, answer):
    bundle, system, _, query = prepared
    (bundle / "_internal/libssl.so.3").write_bytes(b"same")
    (system / "libssl.so.3").write_bytes(b"same")
    def respond(args, **kwargs):
        if args[1] == "--search":
            return query(args, **kwargs)
        return subprocess.CompletedProcess(args, 1 if answer is None else 0, answer or "", "")
    monkeypatch.setattr(inventory.subprocess, "run", respond)
    row = inventory.native(bundle, "linux-x64", [])["systemComponents"][0]
    assert row["status"] == "unresolved" and row["reason"]
    assert "package" not in row and "version" not in row


def test_dpkg_absence_is_unresolved_without_guessing_an_openssl_version(prepared, monkeypatch):
    bundle, _, _, _ = prepared
    (bundle / "_internal/libcrypto.so.3").write_bytes(b"same")
    def absent(*args, **kwargs):
        raise FileNotFoundError("synthetic unavailable package manager")
    monkeypatch.setattr(inventory.subprocess, "run", absent)
    row = inventory.native(bundle, "linux-x64", [])["systemComponents"][0]
    assert row["status"] == "unresolved" and row["reason"]
    assert "package" not in row and "version" not in row


def test_multiple_hash_matching_owned_sources_are_unresolved(prepared, monkeypatch):
    bundle, system, _, _ = prepared
    (bundle / "_internal/libssl.so.3").write_bytes(b"same")
    sources = [system / "first/libssl.so.3", system / "second/libssl.so.3"]
    for source in sources:
        source.parent.mkdir()
        source.write_bytes(b"same")
    def ambiguous(args, **kwargs):
        assert args[1] == "--search"
        return subprocess.CompletedProcess(args, 0, "".join(f"libssl3:amd64: {source}\n" for source in sources), "")
    monkeypatch.setattr(inventory.subprocess, "run", ambiguous)
    row = inventory.native(bundle, "linux-x64", [])["systemComponents"][0]
    assert row["status"] == "unresolved" and "ambiguous" in row["reason"].lower()
    assert "package" not in row


@pytest.mark.parametrize("platform", ["windows-x64", "macos-arm64"])
def test_other_platforms_and_unrelated_linux_files_do_not_query_dpkg(prepared, monkeypatch, platform):
    bundle, _, _, _ = prepared
    (bundle / "_internal/libssl.so.3").write_bytes(b"synthetic")
    def unexpected(*args, **kwargs):
        pytest.fail("Non-Linux inventory queried a system package manager")
    monkeypatch.setattr(inventory.subprocess, "run", unexpected)
    assert "systemComponents" not in inventory.native(bundle, platform, [])
    (bundle / "_internal/libssl.so.3").rename(bundle / "_internal/unrelated.so")
    assert inventory.native(bundle, "linux-x64", [])["systemComponents"] == []


def test_system_package_metadata_never_expands_the_supported_osv_query_scope(tmp_path, monkeypatch):
    source = tmp_path / "inventory.json"
    source.write_text(json.dumps({"packages": [{"ecosystem": "PyPI", "name": "synthetic", "version": "1.2.3"}],
        "systemComponents": [{"status": "matched", "package": "libssl3:amd64", "version": "3.0.2-0ubuntu1.20"}]}))
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"results":[{}]}'
    def respond(request, **kwargs):
        requests.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr(inventory.urllib.request, "urlopen", respond)
    inventory.audit([source], tmp_path / "audit.json")
    assert requests == [{"queries": [{"package": {"ecosystem": "PyPI", "name": "synthetic"}, "version": "1.2.3"}]}]


@pytest.mark.parametrize("ownership", ["diversion by replacement from: {source}\nlibssl3:amd64: {source}\n",
    "libssl3:amd64: relative/libssl.so.3\n", "libssl3:amd64, replacement:amd64: {source}\n",
    "libssl3:amd64: {source}.different\n"])
def test_unrecognized_or_diverted_ownership_cannot_attribute_a_matching_file(prepared, monkeypatch, ownership):
    bundle, system, _, _ = prepared
    (bundle / "_internal/libssl.so.3").write_bytes(b"same")
    source = system / "libssl.so.3"
    source.write_bytes(b"same")
    def respond(args, **kwargs):
        assert args[1] == "--search"
        return subprocess.CompletedProcess(args, 0, ownership.format(source=source), "")
    monkeypatch.setattr(inventory.subprocess, "run", respond)
    row = inventory.native(bundle, "linux-x64", [])["systemComponents"][0]
    assert row["status"] == "unresolved" and row["reason"]
    assert "package" not in row and "version" not in row


def test_system_file_change_during_package_lookup_invalidates_provenance(prepared, monkeypatch):
    bundle, system, _, query = prepared
    (bundle / "_internal/libssl.so.3").write_bytes(b"same")
    source = system / "libssl.so.3"
    source.write_bytes(b"same")
    def respond(args, **kwargs):
        result = query(args, **kwargs)
        if args[1] == "--show":
            source.write_bytes(b"changed during package lookup")
        return result
    monkeypatch.setattr(inventory.subprocess, "run", respond)
    row = inventory.native(bundle, "linux-x64", [])["systemComponents"][0]
    assert row["status"] == "unresolved" and "changed" in row["reason"]
    assert "package" not in row and "version" not in row
