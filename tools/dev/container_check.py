"""Check the public devcontainer's mounted daemon and tools without signing in."""
from pathlib import Path
import json
import shutil
import stat
import subprocess
import sys


def check(socket_path='/var/run/docker-host.sock', *, runner=subprocess.run, locate=shutil.which):
    try:
        mounted=stat.S_ISSOCK(Path(socket_path).stat().st_mode)
    except FileNotFoundError:
        mounted=False
    if not mounted:
        raise RuntimeError('Host Docker socket mount is missing or is a regular file. Recreate the devcontainer to apply its configured bind mount.')
    for tool in ('docker','gh'):
        if locate(tool) is None:
            raise RuntimeError(tool+' executable is missing. Rebuild the configured public devcontainer.')
    result={}
    for label,args in [('Docker daemon',['docker','info','--format','{{.ServerVersion}}']),('GitHub CLI',['gh','--version'])]:
        try:
            process=runner(args,capture_output=True,text=True,timeout=15,check=False)
        except (OSError,subprocess.TimeoutExpired) as error:
            raise RuntimeError(label+' check could not complete. Inspect the mounted socket and CLI installation.') from error
        if process.returncode!=0 or not process.stdout.strip():
            raise RuntimeError(label+' check failed. Inspect the Docker context/socket or rebuild the CLI installation.')
        result['dockerServer' if label=='Docker daemon' else 'githubCli']=process.stdout.splitlines()[0].strip()
    return result


def main():
    try:
        print(json.dumps(check()))
        return 0
    except RuntimeError as error:
        print('Devcontainer check: '+str(error),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
