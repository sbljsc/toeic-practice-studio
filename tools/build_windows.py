"""Build a runtime-included Windows ZIP from an explicit public payload.

Build tools belong to the maintainer's environment. The resulting package never
downloads dependencies, invokes a system Python/Node, or carries learner data.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [
    'README.md', 'LICENSE.md', 'CONTENT-NOTICE.md', 'THIRD-PARTY-NOTICES.txt',
    'docs/architecture.md', 'docs/acceptance.md', 'docs/windows.md',
    'docs/images/workspace-report.jpg', 'docs/images/question-bank.jpg',
]


def sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def safe_relative(name):
    """Accept only portable, unambiguous Windows-relative archive members."""
    value = name.rstrip('/')
    if (not value or '\\' in value or ':' in value or
            PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive or
            any(part in {'', '.', '..'} or part.endswith((' ', '.'))
                for part in value.split('/'))):
        raise ValueError('unsafe relative package path')
    for part in value.split('/'):
        if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I):
            raise ValueError('reserved Windows package path')
    return PurePosixPath(value)


def is_link(path):
    return path.is_symlink() or path.is_junction()


def reject_linked_ancestors(path):
    if any(is_link(parent) for parent in [path, *path.parents]):
        raise ValueError('build destination must not contain linked ancestors')


def checked_file(root, name):
    relative = safe_relative(name)
    path = root.joinpath(*relative.parts)
    if (not path.is_file() or not path.resolve().is_relative_to(root.resolve()) or
            any(is_link(parent) for parent in [path, *path.parents] if parent != root.parent)):
        raise ValueError('missing or linked payload file: ' + name)
    return path


def collect_payload(root):
    files = [checked_file(root, name) for name in DOCUMENTS + ['Start.cmd']]
    api = root / 'apps/api/src'
    api_files = [p for p in api.rglob('*.py') if '__pycache__' not in p.parts]
    if not api_files:
        raise ValueError('API source is missing')
    files += [checked_file(root, p.relative_to(root).as_posix()) for p in api_files]
    web = root / 'apps/web/dist'
    checked_file(root, 'apps/web/dist/index.html')
    for path in web.rglob('*'):
        if path.is_file():
            name = path.relative_to(web).as_posix()
            if name != 'index.html' and not re.fullmatch(r'assets/[\w-]+\.(js|css)', name):
                raise ValueError('unexpected web build file: ' + name)
            files.append(checked_file(root, path.relative_to(root).as_posix()))
    bank = root / 'content/question-pool'
    manifest = json.loads(checked_file(root, 'content/question-pool/manifest.json').read_text(encoding='utf-8'))
    expected = {'manifest.json', 'pool.json'} | {str(safe_relative(a['path'])) for a in manifest['assets']}
    # The readable question tree sits beside the shared picture and recording
    # pools. Its files are the bank itself, so they belong in the payload.
    parts = bank / 'parts'
    if parts.is_dir():
        expected |= {p.relative_to(bank).as_posix() for p in parts.rglob('*') if p.is_file()}
    actual = {p.relative_to(bank).as_posix() for p in bank.rglob('*') if p.is_file()}
    if actual != expected:
        raise ValueError('missing or unregistered content file')
    files += [checked_file(root, 'content/question-pool/' + name) for name in sorted(expected)]
    return sorted(set(files))


def extract_runtime(archive, target):
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        seen = set()
        for item in entries:
            name = str(safe_relative(item.filename))
            if name.casefold() in seen or ((item.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError('duplicate or linked runtime entry')
            seen.add(name.casefold())
        # Validate every member before creating the destination or extracting.
        target.mkdir(parents=True, exist_ok=False)
        source.extractall(target)


def configure_runtime(runtime):
    runtime.mkdir(parents=True, exist_ok=True)
    # ._pth also excludes registry/PYTHONHOME/PYTHONPATH and user site-packages.
    # No import-site line: dependencies are vendored, not installed on startup.
    (runtime / 'python314._pth').write_text(
        'python314.zip\n.\nLib/site-packages\n../apps/api/src\n', encoding='utf-8')


def make_archive(stage, output, prefix):
    safe_relative(prefix)
    files = sorted(p for p in stage.rglob('*') if p.is_file())
    for path in files:
        name = path.relative_to(stage).as_posix()
        checked_file(stage, name)
        parts = {part.casefold() for part in path.relative_to(stage).parts}
        if (parts & {'.data', '.git', '.venv', 'node_modules', '__pycache__', '.env', 'scripts', 'bin'} or
                path.suffix.lower() in {'.sqlite', '.sqlite3', '.db', '.bak', '.log', '.pyc', '.pyo', '.pdf', '.docx'}):
            raise ValueError('private or build-only file in package: ' + name)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, prefix + '/' + path.relative_to(stage).as_posix())


def download_runtime(settings, cache):
    reject_linked_ancestors(cache)
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / ('python-' + settings['version'] + '-embed-amd64.zip')
    if is_link(archive) or is_link(cache):
        raise ValueError('runtime cache must not be linked')
    if not archive.exists():
        if not settings['url'].startswith('https://www.python.org/ftp/python/'):
            raise ValueError('runtime URL must be an official HTTPS download')
        request = urllib.request.Request(settings['url'], headers={'User-Agent': 'TOEIC-Practice-Studio-builder'})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open('xb') as output:
            shutil.copyfileobj(response, output)
    if sha256(archive) != settings['sha256']:
        raise ValueError('official Python runtime SHA-256 mismatch; cache was preserved for inspection')
    return archive


def validate_version(root, version):
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('version must be a semantic version without a leading v')
    web = json.loads((root / 'package.json').read_text(encoding='utf-8'))['version']
    api = tomllib.loads((root / 'apps/api/pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    if version != web or version != api:
        raise ValueError('release version must match package.json and API pyproject.toml')


def build_web(root):
    npm, node = shutil.which('npm.cmd'), shutil.which('node.exe')
    if not npm or not node:
        raise ValueError('the build machine needs Node.js 24+ and npm; end users do not')
    node_version = subprocess.check_output([node, '--version'], text=True).strip()
    if int(node_version.lstrip('v').split('.')[0]) < 24:
        raise ValueError('the build machine needs Node.js 24+')
    npm_version = subprocess.check_output([npm, '--version'], text=True).strip()
    subprocess.run([npm, 'ci'], cwd=root, check=True)
    subprocess.run([npm, 'run', 'web:build'], cwd=root, check=True)
    return {'node': node_version, 'npm': npm_version}


def publish_archive(stage, output, prefix):
    """Expose complete, CRC-checked files with exclusive names, never partial ZIPs."""
    checksum = output.with_suffix('.zip.sha256')
    if output.exists() or checksum.exists() or is_link(output) or is_link(checksum):
        raise FileExistsError('release archive or checksum already exists')
    reject_linked_ancestors(output.parent)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(tempfile.mkdtemp(prefix='.release-', dir=output.parent)).resolve()
    temporary_zip = partial / output.name
    temporary_sha = partial / checksum.name
    make_archive(stage, temporary_zip, prefix)
    with zipfile.ZipFile(temporary_zip) as archive:
        if archive.testzip() is not None:
            raise ValueError('release ZIP CRC validation failed')
    temporary_sha.write_text(sha256(temporary_zip) + '  ' + output.name + '\n', encoding='ascii')
    # Hard links create an exclusive final name in one operation. Both files
    # are fully written first; a second publication failure rolls back only
    # our own first link. Existing destinations are never replaced.
    os.link(temporary_zip, output)
    try:
        os.link(temporary_sha, checksum)
    except OSError:
        if output.exists() and not is_link(output) and output.samefile(temporary_zip):
            output.unlink()
        raise
    temporary_zip.unlink()
    temporary_sha.unlink()
    partial.rmdir()
    return checksum


def source_revision(root, allow_dirty):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    revision = git('rev-parse', 'HEAD')
    dirty = bool(git('status', '--porcelain', '--untracked-files=normal'))
    if dirty and not allow_dirty:
        raise ValueError('commit reviewed source changes first, or use --allow-dirty for a local trial only')
    return revision, dirty


def build(root, version, output_dir, allow_dirty=False):
    if os.name != 'nt' or platform.machine().upper() not in {'AMD64', 'X86_64'} or sys.version_info[:2] != (3, 14):
        raise ValueError('build on Windows x64 with CPython 3.14; end users need no installed runtime')
    validate_version(root, version)
    cache = root / '.data/build-cache/windows'
    build_root = root / '.data/windows-build'
    for path in (cache, build_root, output_dir):
        reject_linked_ancestors(path)
    if not build_root.resolve().is_relative_to(root.resolve()):
        raise ValueError('build staging must remain inside the project data directory')
    name = 'TOEIC-Practice-Studio-' + version + '-windows-x64'
    output = output_dir / (name + '.zip')
    if output.exists() or output.with_suffix('.zip.sha256').exists():
        raise FileExistsError('release archive or checksum already exists')
    revision, dirty = source_revision(root, allow_dirty)
    build_tools = build_web(root)
    files = collect_payload(root)
    subprocess.run([sys.executable, str(root / 'tools/check_bundle.py')], cwd=root, check=True)
    settings = json.loads((root / 'tools/windows-runtime.json').read_text(encoding='utf-8'))
    archive = download_runtime(settings, cache)
    build_root.mkdir(parents=True, exist_ok=True)
    # Retain private staging for inspection; never delete or overwrite a user's directory.
    workspace = Path(tempfile.mkdtemp(prefix='candidate-', dir=build_root)).resolve()
    stage = workspace / 'package'
    stage.mkdir()
    for source in files:
        destination = stage / source.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    runtime = stage / 'runtime'
    extract_runtime(archive, runtime)
    configure_runtime(runtime)
    vendor = workspace / 'vendor'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-compile', '--no-warn-script-location',
                    '--only-binary=:all:', '--require-hashes', '--target', str(vendor),
                    '-r', str(root / 'apps/api/requirements.lock')], check=True)
    packages = runtime / 'Lib/site-packages'
    packages.mkdir(parents=True)
    for path in vendor.iterdir():
        # pip's generated command wrappers embed the build interpreter path and
        # are unnecessary: the application invokes modules directly.
        if path.name.casefold() in {'bin', 'scripts', '__pycache__'}:
            continue
        if is_link(path):
            raise ValueError('linked vendored dependency')
        if path.is_dir():
            shutil.copytree(path, packages / path.name)
        else:
            shutil.copy2(path, packages / path.name)
    distributions = sorted(
        ({'name': d.metadata['Name'], 'version': d.version}
         for d in importlib.metadata.distributions(path=[str(packages)])), key=lambda d: d['name'].lower())
    info = {
        'application': 'TOEIC Practice Studio', 'version': version, 'platform': 'windows-x64',
        'source_commit': revision, 'source_dirty': dirty,
        'build_tools': build_tools,
        'web_assets': {p.relative_to(stage / 'apps/web/dist').as_posix(): sha256(p)
                       for p in sorted((stage / 'apps/web/dist').rglob('*')) if p.is_file()},
        'python': settings, 'runtime_requirements_sha256': sha256(root / 'apps/api/requirements.lock'),
        'pool_sha256': sha256(stage / 'content/question-pool/pool.json'),
        'dependencies': distributions,
    }
    (stage / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    with (stage / 'THIRD-PARTY-NOTICES.txt').open('a', encoding='utf-8') as notices:
        notices.write('\n\nBUNDLED CPYTHON RUNTIME\nPython ' + settings['version'] +
                      ' Windows x64 embeddable distribution from python.org.\n'
                      'The runtime license and included third-party notices are in runtime/LICENSE.txt.\n'
                      'Its module search path is customized for this application.\n')
    # Verify imports, runtime identity and path discovery with the bundled interpreter.
    probe = subprocess.check_output([str(runtime / 'python.exe'), '-B', '-X', 'utf8', '-c',
        "import sys,sqlite3,uvicorn,fastapi,pydantic_core; from toeic_practice import config; "
        "assert config.WEB_DIST.is_dir(); assert (config.library_dir()/'manifest.json').is_file(); "
        "assert sys.flags.isolated and sys.flags.no_site; print(sys.version.split()[0])"],
        cwd=workspace, text=True).strip()
    if probe != settings['version']:
        raise ValueError('bundled interpreter version does not match the pinned runtime')
    if source_revision(root, allow_dirty) != (revision, dirty):
        raise ValueError('source revision or clean state changed during the build')
    checksum = publish_archive(stage, output, 'TOEIC-Practice-Studio')
    result = {'status': 'BUILT', 'artifact': str(output), 'checksum': str(checksum),
              'bytes': output.stat().st_size, 'source_commit': revision, 'source_dirty': dirty,
              'python': probe, 'staging': str(stage)}
    (workspace / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description='Build a self-contained Windows x64 portable ZIP.')
    parser.add_argument('--version', required=True, help='release version, for example 0.1.0')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist/releases')
    parser.add_argument('--allow-dirty', action='store_true', help='local trial only; never publish a dirty build')
    args = parser.parse_args()
    build(ROOT, args.version, args.output_dir.resolve(), args.allow_dirty)


if __name__ == '__main__':
    main()
