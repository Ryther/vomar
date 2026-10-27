"""Native build admission rejects unsupported hosts before creating state."""
import pytest
from tools.release import package_desktop


@pytest.mark.parametrize('machine',['x86_64','AMD64'])
def test_intel_macos_build_rejects_before_output_or_network(tmp_path,monkeypatch,machine):
    monkeypatch.setattr(package_desktop.platform,'system',lambda:'Darwin')
    monkeypatch.setattr(package_desktop.platform,'machine',lambda:machine)
    def unexpected_fetch(*args):
        pytest.fail('Unsupported Intel build attempted a network download')
    monkeypatch.setattr(package_desktop,'fetch',unexpected_fetch)
    output=tmp_path/'native'
    with pytest.raises(ValueError,match='macOS.*Apple Silicon.*arm64'):
        package_desktop.build(output,'0.1.0')
    assert not output.exists()


@pytest.mark.parametrize('system,machine',[('Linux','x86_64'),('Windows','AMD64'),('Darwin','arm64'),('Darwin','aarch64')])
def test_supported_hosts_continue_to_normal_version_validation(tmp_path,monkeypatch,system,machine):
    monkeypatch.setattr(package_desktop.platform,'system',lambda:system)
    monkeypatch.setattr(package_desktop.platform,'machine',lambda:machine)
    output=tmp_path/'native'
    with pytest.raises(ValueError,match='Distribution SemVer required'):
        package_desktop.build(output,'invalid-version')
    assert not output.exists()
