"""Read-only runtime identity and disposable loopback TLS checks."""
import json
import errno
import ssl

import pytest

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
    assert result['untrustedCertificateError']['type']=='SSLCertVerificationError'
    assert result['untrustedCertificateError']['verifyCode']>0
    assert result['negotiatedTlsVersion'] in ('TLSv1.2', 'TLSv1.3')


def test_tls_self_test_requires_explicit_runtime_info(monkeypatch):
    with pytest.raises(SystemExit) as error:cli.main(['--tls-self-test'])
    assert error.value.code == 2


def server_transport_error(monkeypatch, error, *, phase='untrusted'):
    """Simulate only the server transport; real clients still validate real certs."""
    original=ssl.SSLContext.wrap_socket;calls=[]
    def wrap(context, socket, *args, **kwargs):
        if not kwargs.get('server_side'):return original(context,socket,*args,**kwargs)
        current='trusted' if not calls else 'untrusted';calls.append(current)
        if current==phase:
            if phase=='trusted':raise error
            try:return original(context,socket,*args,**kwargs)
            except ssl.SSLError:raise error from None
        return original(context,socket,*args,**kwargs)
    monkeypatch.setattr(ssl.SSLContext,'wrap_socket',wrap)
    return calls


def test_windows_negative_handshake_reset_requires_actual_client_certificate_rejection(monkeypatch):
    reset=ConnectionResetError(10054,'An existing connection was forcibly closed by the remote host')
    reset.winerror=10054
    calls=server_transport_error(monkeypatch,reset)
    result=runtime_info.tls_self_test()
    assert calls==['trusted','untrusted']
    assert result['trustedCertificateAccepted'] is True
    assert result['untrustedCertificateRejected'] is True
    assert result['untrustedCertificateError']['type']=='SSLCertVerificationError'


def test_trusted_handshake_reset_remains_fatal_and_diagnostic(monkeypatch):
    server_transport_error(monkeypatch,ConnectionResetError(errno.ECONNRESET,'Synthetic trusted reset'),phase='trusted')
    with pytest.raises(ValueError) as error:runtime_info.tls_self_test()
    assert 'trusted' in str(error.value) and 'ConnectionResetError' in str(error.value)


@pytest.mark.parametrize('error',[PermissionError(errno.EACCES,'Synthetic permission failure'),
                                 ConnectionAbortedError(10053,'Synthetic aborted handshake')])
def test_other_negative_handshake_errors_remain_fatal_and_diagnostic(monkeypatch,error):
    server_transport_error(monkeypatch,error)
    with pytest.raises(ValueError) as failure:runtime_info.tls_self_test()
    assert 'untrusted' in str(failure.value) and 'handshake' in str(failure.value)
    assert type(error).__name__ in str(failure.value)


def test_server_reset_cannot_replace_the_client_certificate_error(monkeypatch):
    server_transport_error(monkeypatch,ConnectionResetError(10054,'Synthetic server reset'))
    original=ssl.SSLContext.wrap_socket
    def client_transport_error(context,socket,*args,**kwargs):
        try:return original(context,socket,*args,**kwargs)
        except ssl.SSLCertVerificationError:
            raise ConnectionResetError(errno.ECONNRESET,'Synthetic client transport failure') from None
    monkeypatch.setattr(ssl.SSLContext,'wrap_socket',client_transport_error)
    with pytest.raises(ValueError) as error:runtime_info.tls_self_test()
    assert '"clientCertificateRejected": false' in str(error.value)
    assert 'Synthetic client transport failure' in str(error.value)
