"""Read-only runtime identity and disposable loopback TLS checks."""
import json

from vomar_updater import cli
from vomar_updater import runtime_info


def test_runtime_info_cli_does_not_construct_service_or_touch_state(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):raise AssertionError('Runtime info must not construct Service')
    monkeypatch.setattr(cli, 'Service', forbidden)
    state = tmp_path / 'state'
    assert cli.main(['--state', str(state), '--runtime-info']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['pythonVersion'] and result['opensslVersion'].startswith('OpenSSL ')
    assert 'tlsSelfTest' not in result and not state.exists()


def test_explicit_tls_self_test_trusts_its_ca_and_rejects_an_untrusted_ca():
    result = runtime_info.tls_self_test()
    assert result['address'] == '127.0.0.1'
    assert result['trustedCertificateAccepted'] is True
    assert result['untrustedCertificateRejected'] is True
    assert result['negotiatedTlsVersion'] in ('TLSv1.2', 'TLSv1.3')


def test_tls_self_test_requires_explicit_runtime_info(monkeypatch):
    import pytest
    with pytest.raises(SystemExit) as error:cli.main(['--tls-self-test'])
    assert error.value.code == 2
