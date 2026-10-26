"""Build the site from Git-admitted docs, resolving source links back to GitHub."""
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def on_config(config):
    output = ROOT/'_test/docs-source'
    if output.is_symlink():
        raise ValueError('Documentation staging must not be a symlink')
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    paths = subprocess.check_output([
        'git', '-C', str(ROOT), 'ls-files', '-z', '--cached', '--others',
        '--exclude-standard', '--', 'docs',
    ]).decode().split('\0')
    for name in sorted(set(paths)-{''}):
        source = ROOT/name
        if source.is_symlink():
            raise ValueError('Documentation source must not be a symlink: '+name)
        target = output/source.relative_to(ROOT/'docs')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    config.docs_dir = str(output)
    return config


def on_page_markdown(markdown, page, config, files):
    source = ROOT/'docs'/page.file.src_uri
    def replace(match):
        link = match.group(1)
        url = urlsplit(link)
        if url.scheme or url.netloc or not url.path or url.path.startswith('/'):
            return match.group(0)
        target = (source.parent/url.path).resolve()
        if target.is_relative_to((ROOT/'docs').resolve()):
            return match.group(0)
        if not target.is_relative_to(ROOT.resolve()) or not target.exists():
            return match.group(0)  # Strict MkDocs reports invalid links.
        relative = target.relative_to(ROOT.resolve()).as_posix()
        remote = config.repo_url.rstrip('/')+'/blob/main/'+quote(relative)
        if url.fragment:
            remote += '#'+url.fragment
        return ']('+remote+')'
    return re.sub(r'\]\(([^\s)]+)\)', replace, markdown)
