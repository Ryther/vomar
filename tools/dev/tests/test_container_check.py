"""Regression for a live proxy forwarding into an unmounted socket placeholder."""
import socket
from pathlib import Path
from types import SimpleNamespace
import pytest


def test_placeholder_is_rejected_before_cli_or_daemon_calls(tmp_path):
    from tools.dev.container_check import check
    path=tmp_path/'docker-host.sock';path.touch();calls=[]
    def run(*a,**k):calls.append(a);raise AssertionError('A placeholder must fail before Docker invocation')
    with pytest.raises(RuntimeError,match='socket.*mount'):check(path,runner=run)
    assert not calls


def test_actual_socket_requires_both_tools_and_a_live_daemon(tmp_path):
    from tools.dev.container_check import check
    path=tmp_path/'host.sock';listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    try:
        listener.bind(str(path));calls=[]
        def run(args,**kwargs):calls.append(args);return SimpleNamespace(returncode=0,stdout='' if args[0]=='ssh' else '29.9.2\n' if args[0]=='docker' else 'gh version 2.103.2\n',stderr='OpenSSH client\n' if args[0]=='ssh' else '')
        assert check(path,runner=run,locate=lambda tool:'/usr/bin/'+tool)=={'dockerServer':'29.9.2','githubCli':'gh version 2.103.2','sshClient':'OpenSSH client'}
        assert calls==[['docker','info','--format','{{.ServerVersion}}'],['gh','--version'],['ssh','-V']]
        with pytest.raises(RuntimeError,match='gh.*missing'):check(path,runner=run,locate=lambda tool:None if tool=='gh' else tool)
        with pytest.raises(RuntimeError,match='Docker daemon'):check(path,runner=lambda *a,**k:SimpleNamespace(returncode=1,stdout='',stderr='EOF'),locate=lambda tool:tool)
    finally:listener.close()


def test_missing_ssh_client_is_rejected_without_contacting_github(tmp_path):
    from tools.dev.container_check import check
    path=tmp_path/'host.sock';listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        with pytest.raises(RuntimeError,match='ssh executable is missing'):
            check(path,locate=lambda tool:None if tool=='ssh' else '/usr/bin/'+tool,
                  runner=lambda *a,**k:SimpleNamespace(returncode=0,stdout='installed\n',stderr=''))
    finally:listener.close()
