"""Build the task-oriented public site from canonical product documents only."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[2]
PAGES=('index.md','development.md','desktop.md','offline-guide.md','releasing.md','github-setup.md','desktop-parity.md','ux-evidence.md')
def on_config(config):
    output=ROOT/'_test/docs-source';output.mkdir(parents=True,exist_ok=True)
    for name in PAGES:shutil.copy2(ROOT/'docs'/name,output/name)
    config.docs_dir=str(output);return config
