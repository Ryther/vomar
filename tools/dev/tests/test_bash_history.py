"""Exercise shared history with real interactive shells and disposable state."""

import os
import select
import subprocess
from pathlib import Path


def test_history_is_saved_before_exit_and_shared_between_open_shells(tmp_path):
    root = Path(__file__).resolve().parents[3]
    history = tmp_path / 'history'
    history.write_text('older_history_marker\n')
    rc = tmp_path / 'bashrc'
    rc.write_text(
        "PROMPT_COMMAND=('true')\n"
        f"source '{root}/.devcontainer/bash-history.sh'\n"
        f"HISTFILE='{history}'\n"
    )
    shells = []

    def command(shell, text):
        shell.stdin.write(text + "\nprintf 'READY\\n'\n")
        shell.stdin.flush()
        assert select.select([shell.stdout], [], [], 5)[0], 'Shell did not respond'
        assert os.read(shell.stdout.fileno(), 4096) == b'READY\n'

    try:
        for _ in range(2):
            shell = subprocess.Popen(
                ['bash', '--noprofile', '--rcfile', str(rc), '-i'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True,
            )
            shells.append(shell)
            command(shell, 'true')
        command(shells[0], ': synthetic_history_marker')
        assert 'synthetic_history_marker' in history.read_text()
        assert 'older_history_marker' in history.read_text()
        command(shells[1], 'true')
        command(shells[1], "history | grep -q '^ *[0-9]* *: synthetic_history_marker$' || printf 'MISSING\\n'")
        command(shells[0], f"source '{root}/.devcontainer/bash-history.sh'; HISTFILE='{history}'")
        command(shells[0], '[[ ${#PROMPT_COMMAND[@]} == 2 ]] || printf "DUPLICATE\\n"')
    finally:
        for shell in shells:
            shell.stdin.close()
            shell.wait(timeout=5)
            shell.stdout.close()
