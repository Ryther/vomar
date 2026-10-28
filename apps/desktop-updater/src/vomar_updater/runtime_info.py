"""Read-only runtime identity and an explicitly requested disposable TLS check."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import itertools
import json
from pathlib import Path
import socket
import re
import ssl
import sys
import tempfile
import threading

from . import __version__


def runtime_info():
    defaults = ssl.get_default_verify_paths()
    trust = ssl.create_default_context().cert_store_stats()
    # OpenSSL loads hashed CA directories lazily, so zero cached certificates
    # alone does not mean that the platform default trust store is empty.
    hashed = 0
    for name in (defaults.capath or '').split(os.pathsep):
        directory = Path(name) if name else None
        if directory is not None and directory.is_dir():
            hashed += sum(1 for entry in itertools.islice(directory.iterdir(), 10000)
                          if re.fullmatch(r'[0-9a-fA-F]{8}\.[0-9]+', entry.name) and entry.is_file())
    return {'schemaVersion': 1, 'nativeVersion': __version__,
            'pythonVersion': '.'.join(map(str, sys.version_info[:3])),
            'opensslVersion': ssl.OPENSSL_VERSION,
            'frozen': getattr(sys, 'frozen', False) is True,
            'defaultTrustStore': {'caCertificates': trust['x509_ca'], 'hashedCaFiles': hashed,
                'compiledCafile': defaults.openssl_cafile, 'compiledCapath': defaults.openssl_capath,
                'cafilePresent': defaults.cafile is not None, 'capathPresent': defaults.capath is not None,
                'userCafileOverride': defaults.openssl_cafile_env in os.environ,
                'userCapathOverride': defaults.openssl_capath_env in os.environ}}


def _certificates(directory):
    """Fresh test-only certificates; no existing credential store is consulted."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.now(timezone.utc)
    def certificate(name, key, issuer, signer, *, ca):
        builder = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
                   .issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
                   .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()), critical=False)
                   .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                       key_encipherment=False, data_encipherment=False, key_agreement=False,
                       key_cert_sign=ca, crl_sign=ca, encipher_only=None, decipher_only=None), critical=True))
        if not ca:builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
        return builder.sign(signer, hashes.SHA256())

    trusted = ec.generate_private_key(ec.SECP256R1())
    trusted_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Vomar disposable trusted CA')])
    ca = certificate('Vomar disposable trusted CA', trusted, trusted_name, trusted, ca=True)
    leaf = ec.generate_private_key(ec.SECP256R1())
    server = certificate('localhost', leaf, ca.subject, trusted, ca=False)
    for name, cert in [('ca.pem', ca), ('server.pem', server)]:
        (directory / name).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key = directory / 'server-key.pem'
    with key.open('xb') as stream:
        stream.write(leaf.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key.chmod(0o600)


def tls_self_test():
    """Bounded loopback-only TLS admission; never accesses devices or brokers."""
    with tempfile.TemporaryDirectory(prefix='vomar-tls-') as temporary:
        directory = Path(temporary);_certificates(directory)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.minimum_version = ssl.TLSVersion.TLSv1_2
        server_context.load_cert_chain(directory / 'server.pem', directory / 'server-key.pem')
        errors = [];completed = [];server_rejections = []
        client_rejected = False;client_rejection = None;client_error = None;client_phase = 'trusted';negotiated = None
        def failure(error, expected, phase):
            return {'connection':expected,'phase':phase,'type':type(error).__name__,
                    'errno':getattr(error,'errno',None),'winerror':getattr(error,'winerror',None),
                    'message':str(error)}
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0));listener.listen(2);listener.settimeout(5)
            address = listener.getsockname()
            def serve():
                expected='trusted';phase='accept'
                try:
                    for expected in ('trusted', 'untrusted'):
                        phase='accept'
                        connection, _ = listener.accept()
                        with connection:
                            connection.settimeout(5)
                            try:
                                phase='handshake'
                                with server_context.wrap_socket(connection, server_side=True) as secured:
                                    phase='response'
                                    secured.sendall(b'Vomar TLS test\n');completed.append(expected)
                            except (ssl.SSLError,ConnectionResetError) as error:
                                if expected!='untrusted' or phase!='handshake':raise
                                # Windows can surface the peer's certificate-rejection
                                # close as WSAECONNRESET instead of a TLS alert. This
                                # server observation never substitutes for the client's
                                # actual SSLCertVerificationError below.
                                server_rejections.append(failure(error,expected,phase))
                except (OSError, RuntimeError) as error:errors.append(failure(error,expected,phase))
            worker = threading.Thread(target=serve, name='vomar-local-tls', daemon=True);worker.start()
            try:
                trusted_context = ssl.create_default_context()
                trusted_context.load_verify_locations(cafile=str(directory / 'ca.pem'))
                trusted_context.minimum_version = ssl.TLSVersion.TLSv1_2
                with socket.create_connection(address, timeout=5) as connection:
                    with trusted_context.wrap_socket(connection, server_hostname='localhost') as secured:
                        if secured.recv(64) != b'Vomar TLS test\n':raise ValueError('Local TLS self-test response mismatch')
                        negotiated = secured.version()
                client_phase='untrusted'
                unrelated_context = ssl.create_default_context()
                unrelated_context.minimum_version = ssl.TLSVersion.TLSv1_2
                try:
                    with socket.create_connection(address, timeout=5) as connection:
                        with unrelated_context.wrap_socket(connection, server_hostname='localhost'):
                            raise ValueError('Local TLS self-test accepted an untrusted certificate')
                except ssl.SSLCertVerificationError as error:
                    client_rejected=True
                    client_rejection={'type':type(error).__name__,'verifyCode':getattr(error,'verify_code',None),
                                      'verifyMessage':getattr(error,'verify_message',None)}
            except (OSError,ValueError) as error:client_error=error
            finally:
                worker.join(timeout=6)
            if client_error is not None or worker.is_alive() or errors or completed!=['trusted'] or not client_rejected or len(server_rejections)!=1:
                details={'completed':completed,'clientCertificateRejected':client_rejected,
                         'clientCertificateError':client_rejection,
                         'clientError':failure(client_error,client_phase,'client') if client_error is not None else None,
                         'serverErrors':errors,'serverRejections':server_rejections,'workerAlive':worker.is_alive()}
                raise ValueError('Local TLS self-test did not complete safely: '+json.dumps(details,sort_keys=True)) from client_error
        return {'address': '127.0.0.1', 'trustedCertificateAccepted': True,
                'untrustedCertificateRejected': True, 'untrustedCertificateError':client_rejection,
                'negotiatedTlsVersion': negotiated}
