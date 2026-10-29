"""Native Android versions remain independent of distribution tags."""
import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[3]


def settings():
    config = json.loads((ROOT / "apps/android-updater/obtainium.json").read_text())
    return config, json.loads(config["additionalSettings"])


def test_native_version_tracks_android_across_independent_bundle_releases():
    from tools.release.publish import release_name

    config, options = settings()
    assert config["url"] == "https://github.com/Ryther/vomar"
    assert config.get("overrideSource") is None
    assert options["releaseTitleAsVersion"] is True
    assert options["versionDetection"] is True
    assert options["includePrereleases"] is False
    assert options["includeDrafts"] is False
    assert options["trackOnly"] is False
    for bundle, android in [("1.0.0", "1.1.4"), ("1.1.0", "1.1.4"), ("1.2.0", "1.1.5")]:
        manifest = {"distributionVersion": bundle, "components": {"firmware": "9.0.0", "android": android}}
        title = release_name(manifest)
        found = re.search(options["versionExtractionRegEx"], title)
        assert found is not None
        assert found.group(int(options["matchGroupToUse"].lstrip("$"))) == android
        assert bundle in title
    assert re.search(options["versionExtractionRegEx"], "Vomar bundle 1.0.0") is None


def test_publication_supplies_native_version_title_in_the_publish_request(monkeypatch):
    from tools.release.publish import GitHub, release_name

    remote = GitHub("Ryther/vomar", "synthetic-test-token")
    calls = []
    monkeypatch.setattr(remote, "request", lambda *args: calls.append(args))
    name = release_name({"distributionVersion": "2.0.0", "components": {"android": "1.2.3"}})
    remote.publish(123, name)
    assert calls == [("releases/123", "PATCH", {"draft": False, "make_latest": "true", "name": "Vomar bundle 2.0.0 · Android 1.2.3"})]


@pytest.mark.parametrize("filename, accepted", [
    ("vomar-android-1.0.0.apk", True),
    ("vomar-android-3.2.1.apk", True),
    ("vomar-desktop-1.0.0.apk", False),
    ("vomar-android-1.0.0.apk.sig", False),
    ("other.apk", False),
])
def test_only_the_distribution_android_apk_is_selected(filename, accepted):
    _, options = settings()
    assert bool(re.search(options["apkFilterRegEx"], filename)) is accepted


def test_install_links_import_the_native_tracking_configuration():
    config, _ = settings()
    for name in ["README.md", "docs/android-updater.md", ".agents/skills/vomar-guide/SKILL.md"]:
        text = (ROOT / name).read_text()
        urls = re.findall(r"https://apps\.obtainium\.imranr\.dev/redirect\?r=obtainium://app/([^\s)]+)", text)
        assert urls, f"Missing direct install link: {name}"
        assert all(json.loads(unquote(url)) == config for url in urls)
