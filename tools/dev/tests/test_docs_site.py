"""Public navigation must include approved guides, never ignored local notes."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import subprocess


def test_site_exports_public_guides_and_resolves_source_links(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('docs_site', Path(__file__).parents[2]/'docs/site.py')
    site = importlib.util.module_from_spec(spec); spec.loader.exec_module(site)
    monkeypatch.setattr(site, 'ROOT', tmp_path)
    (tmp_path/'docs').mkdir(); (tmp_path/'firmware').mkdir()
    (tmp_path/'docs/index.md').write_text('# Home\n')
    (tmp_path/'docs/android-updater.md').write_text('# Android\n')
    (tmp_path/'docs/private.md').write_text('private notes')
    (tmp_path/'firmware/main.c').write_text('/* public source */')
    (tmp_path/'.gitignore').write_text('docs/private.md\n')
    subprocess.run(['git','init','-q',str(tmp_path)], check=True)
    subprocess.run(['git','-C',str(tmp_path),'add','docs/index.md','docs/android-updater.md','firmware/main.c','.gitignore'], check=True)
    config = SimpleNamespace(docs_dir='', repo_url='https://github.com/Ryther/vomar')
    site.on_config(config)
    assert (Path(config.docs_dir)/'android-updater.md').is_file()
    assert not (Path(config.docs_dir)/'private.md').exists()
    page = SimpleNamespace(file=SimpleNamespace(src_uri='index.md'))
    result = site.on_page_markdown('[Use](android-updater.md) [Code](../firmware/main.c#L1)', page, config, None)
    assert '[Use](android-updater.md)' in result
    assert 'https://github.com/Ryther/vomar/blob/main/firmware/main.c#L1' in result
