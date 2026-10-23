"""Release helpers must fail closed before producing incomplete/private archives."""
import importlib.util
import zipfile
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'scripts/package_release.py'
spec = importlib.util.spec_from_file_location('release_packaging', MODULE)
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


def test_missing_runtime_rejected_before_packaging(tmp_path):
    with pytest.raises(ValueError, match='runtime/asr/python.exe'):
        pack.validate_portable(tmp_path / 'not-built')
    assert not (tmp_path / 'not-built').exists()


def test_public_source_includes_referenced_environment_installer():
    assert pack.ROOT/'安装环境.ps1' in set(pack.source_files())


def test_source_archive_excludes_stale_stage_files(tmp_path):
    source = tmp_path / 'stage'
    source.mkdir()
    (source / 'README.md').write_text('public', encoding='utf-8')
    (source / 'stale-private.txt').write_text('must not ship', encoding='utf-8')
    result = pack.archive(source, tmp_path / 'source.zip', {'README.md'})
    assert [r['path'] for r in result] == ['README.md']
    with zipfile.ZipFile(tmp_path / 'source.zip') as bundle:
        assert bundle.namelist() == ['stage/README.md']


def test_private_runtime_directories_never_archived(tmp_path):
    stage = tmp_path / 'stage'
    stage.mkdir()
    for folder in ('data', 'models', 'outputs', 'cache', 'qa', '.git'):
        (stage / folder).mkdir()
        (stage / folder / 'private.txt').write_text('private', encoding='utf-8')
    (stage / '.env').write_text('secret', encoding='utf-8')
    (stage / 'portable.json').write_text('{}', encoding='utf-8')
    rows = pack.archive(stage, tmp_path / 'portable.zip')
    assert [r['path'] for r in rows] == ['portable.json']


def test_new_build_removes_old_hashed_assets(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    built = repo / 'frontend/dist'
    built.mkdir(parents=True)
    (built / 'new.js').write_text('new', encoding='utf-8')
    portable = tmp_path / 'portable'
    old = portable / 'frontend/dist'
    old.mkdir(parents=True)
    (old / 'old.js').write_text('old', encoding='utf-8')
    monkeypatch.setattr(pack, 'ROOT', repo)
    monkeypatch.setattr(pack, 'RELEASE', tmp_path)
    monkeypatch.setattr(pack, 'source_files', lambda: iter(()))
    pack.sync_source(portable)
    assert sorted(p.name for p in old.iterdir()) == ['new.js']
