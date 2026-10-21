"""Release boundary checks; no downloads or changes to learner data."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

BUILDER = Path(__file__).with_name('build_windows.py')


def test_windows_builder_has_a_documented_command_line():
    result = subprocess.run([sys.executable, str(BUILDER), '--help'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '--version' in result.stdout and '--output-dir' in result.stdout


@pytest.fixture
def builder():
    spec = importlib.util.spec_from_file_location('windows_builder', BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('name', ['../private', '/absolute', 'C:/private', r'..\private',
                                  r'\\server\share', 'one/../../private', 'a:b', ''])
def test_archive_paths_cannot_escape_the_package(builder, name):
    with pytest.raises(ValueError):
        builder.safe_relative(name)


def test_runtime_extraction_rejects_traversal_before_writing(builder, tmp_path):
    archive = tmp_path / 'runtime.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('python.exe', b'not an executable')
        output.writestr('../outside.txt', b'must not be written')
    target = tmp_path / 'target'
    with pytest.raises(ValueError):
        builder.extract_runtime(archive, target)
    assert not target.exists() and not (tmp_path / 'outside.txt').exists()


def test_runtime_extraction_rejects_duplicate_paths(builder, tmp_path):
    archive = tmp_path / 'runtime.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('python.exe', b'one')
        output.writestr('PYTHON.EXE', b'two')
    with pytest.raises(ValueError):
        builder.extract_runtime(archive, tmp_path / 'runtime')


def test_payload_uses_registered_content_and_explicit_documentation(builder, tmp_path):
    for name in builder.DOCUMENTS + ['Start.cmd', 'apps/api/src/toeic_practice/main.py',
                                     'apps/web/dist/index.html', 'apps/web/dist/assets/app.js']:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('example', encoding='utf-8')
    bank = tmp_path / 'content/question-pool'
    bank.mkdir(parents=True)
    (bank / 'manifest.json').write_text(json.dumps({'assets': [{'path': 'assets/one.flac'}]}))
    (bank / 'pool.json').write_text('{}')
    (bank / 'assets').mkdir()
    (bank / 'assets/one.flac').write_bytes(b'clip')
    for name in ['.data/practice.sqlite3', '.env', 'docs/private.md',
                 'apps/api/src/toeic_practice/__pycache__/main.pyc']:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('private', encoding='utf-8')
    names = {path.relative_to(tmp_path).as_posix() for path in builder.collect_payload(tmp_path)}
    assert 'content/question-pool/assets/one.flac' in names
    assert 'apps/api/src/toeic_practice/main.py' in names
    assert not any('private' in name or '__pycache__' in name or name == '.env' for name in names)
    (bank / 'assets/unregistered.flac').write_bytes(b'not registered')
    with pytest.raises(ValueError, match='unregistered'):
        builder.collect_payload(tmp_path)


def test_payload_carries_the_readable_markdown_question_tree(builder, tmp_path):
    """The bank is a Markdown tree now; the package must ship it."""
    for name in builder.DOCUMENTS + ['Start.cmd', 'apps/api/src/toeic_practice/main.py',
                                     'apps/web/dist/index.html', 'apps/web/dist/assets/app.js']:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('example', encoding='utf-8')
    bank = tmp_path / 'content/question-pool'
    (bank / 'parts/part-3').mkdir(parents=True)
    (bank / 'manifest.json').write_text(json.dumps({'assets': []}), encoding='utf-8')
    (bank / 'pool.json').write_text('{}', encoding='utf-8')
    (bank / 'parts/part-3/g-1.md').write_text('# group', encoding='utf-8')
    (bank / 'parts/part-3/g-1.srt').write_text('1\n', encoding='utf-8')
    names = {path.relative_to(tmp_path).as_posix() for path in builder.collect_payload(tmp_path)}
    assert 'content/question-pool/parts/part-3/g-1.md' in names
    assert 'content/question-pool/parts/part-3/g-1.srt' in names
    # A file outside the Markdown tree and outside the registered assets is
    # still refused, so the package cannot pick up private material.
    (bank / 'private.bin').write_bytes(b'private')
    with pytest.raises(ValueError, match='unregistered'):
        builder.collect_payload(tmp_path)


def test_runtime_path_is_isolated_from_user_and_global_packages(builder, tmp_path):
    builder.configure_runtime(tmp_path)
    paths = (tmp_path / 'python314._pth').read_text(encoding='utf-8').splitlines()
    assert paths == ['python314.zip', '.', 'Lib/site-packages', '../apps/api/src']
    assert not any('import site' in line for line in paths)


def test_archive_refuses_learner_data_and_does_not_overwrite(builder, tmp_path):
    stage = tmp_path / 'stage'
    (stage / '.data').mkdir(parents=True)
    (stage / '.data/practice.sqlite3').write_bytes(b'private')
    output = tmp_path / 'release.zip'
    with pytest.raises(ValueError, match='private'):
        builder.make_archive(stage, output, 'studio')
    assert not output.exists()
    (stage / '.data/practice.sqlite3').unlink()
    (stage / '.data').rmdir()
    (stage / 'Start.cmd').write_text('example')
    builder.make_archive(stage, output, 'studio')
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        builder.make_archive(stage, output, 'studio')
    assert output.read_bytes() == original


def test_release_version_must_match_both_application_versions(builder, tmp_path):
    (tmp_path / 'package.json').write_text('{"version":"0.1.0"}')
    (tmp_path / 'apps/api').mkdir(parents=True)
    (tmp_path / 'apps/api/pyproject.toml').write_text('[project]\nversion="0.1.0"\n')
    builder.validate_version(tmp_path, '0.1.0')
    with pytest.raises(ValueError, match='version'):
        builder.validate_version(tmp_path, '9.0.0')
    (tmp_path / 'apps/api/pyproject.toml').write_text('[project]\nversion="0.2.0"\n')
    with pytest.raises(ValueError, match='version'):
        builder.validate_version(tmp_path, '0.1.0')


def test_cache_link_is_rejected_before_mkdir_or_network(builder, tmp_path, monkeypatch):
    linked_parent = tmp_path / 'cache'
    monkeypatch.setattr(builder, 'is_link', lambda path: Path(path) == linked_parent)
    def unexpected_network(*args, **kwargs):
        raise AssertionError('network attempted before cache validation')
    monkeypatch.setattr(builder.urllib.request, 'urlopen', unexpected_network)
    with pytest.raises(ValueError, match='linked'):
        builder.download_runtime({'version': '3.14.8', 'url': 'https://www.python.org/ftp/python/runtime.zip',
                                  'sha256': '0' * 64}, linked_parent / 'nested')
    assert not linked_parent.exists()


def test_publication_conflict_preserves_existing_checksum(builder, tmp_path):
    stage = tmp_path / 'package'
    stage.mkdir()
    (stage / 'Start.cmd').write_text('start')
    output = tmp_path / 'release.zip'
    checksum = tmp_path / 'release.zip.sha256'
    checksum.write_text('existing release')
    with pytest.raises(FileExistsError):
        builder.publish_archive(stage, output, 'studio')
    assert not output.exists() and checksum.read_text() == 'existing release'


def test_crc_failure_never_exposes_a_final_archive(builder, tmp_path, monkeypatch):
    stage = tmp_path / 'package'
    stage.mkdir()
    (stage / 'Start.cmd').write_text('start')
    output = tmp_path / 'release.zip'
    monkeypatch.setattr(builder.zipfile.ZipFile, 'testzip', lambda self: 'corrupt member')
    with pytest.raises(ValueError, match='CRC'):
        builder.publish_archive(stage, output, 'studio')
    assert not output.exists() and not output.with_suffix('.zip.sha256').exists()


def test_second_publication_failure_rolls_back_only_its_own_link(builder, tmp_path, monkeypatch):
    stage = tmp_path / 'package'
    stage.mkdir()
    (stage / 'Start.cmd').write_text('start')
    output = tmp_path / 'release.zip'
    real_link = builder.os.link
    def fail_second(source, destination):
        if str(destination).endswith('.sha256'):
            raise OSError('simulated second-link failure')
        real_link(source, destination)
    monkeypatch.setattr(builder.os, 'link', fail_second)
    with pytest.raises(OSError, match='second-link'):
        builder.publish_archive(stage, output, 'studio')
    assert not output.exists() and not output.with_suffix('.zip.sha256').exists()
