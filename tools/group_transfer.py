"""Export and import question groups as plain, readable Markdown bundles.

An exported group is one directory that holds the group's Markdown file, the
matching subtitle file, the recording, and any picture the group references.
Importing assigns fresh identifiers so that a bundle can never collide with
the running bank: the new group id is derived from the source group id and
the Markdown content, and each new question id from the source question id
and the new group id.

The frontmatter is parsed with the very same reader the API uses to load the
bank, so an exported bundle always stays readable by the running system.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/src'))

GROUP_ID = re.compile(r'^g-[0-9a-f]{20}$')
QUESTION_ID = re.compile(r'^q-[0-9a-f]{20}$')
ASSET_ID = re.compile(r'^(img|audio)-[0-9a-f]{20}$')


def digest(*parts: str) -> str:
    return hashlib.sha256(':'.join(parts).encode('utf-8')).hexdigest()


def new_group_id(source_group_id: str, content: str) -> str:
    """A group id that keeps the source identity but cannot collide."""
    return 'g-' + digest('group', source_group_id, content)[:20]


def new_question_id(source_question_id: str, new_group: str) -> str:
    """A question id bound to its group, so identical questions stay distinct."""
    return 'q-' + digest('question', source_question_id, new_group)[:20]


def new_asset_id(prefix: str, payload: bytes) -> str:
    """Content-addressed asset id: identical bytes reuse one file."""
    return prefix + '-' + hashlib.sha256(payload).hexdigest()[:20]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split the leading YAML-ish block from the Markdown body."""
    from toeic_practice.md_pool import parse_frontmatter as read_frontmatter

    values = read_frontmatter(text)
    start = text.find('\n---\n', 3)
    if start < 0:
        raise ValueError('frontmatter 未闭合')
    return values, text[start + 5:]


def frontmatter_lines(data: dict) -> str:
    """Serialize the frontmatter block in the shape the bank uses."""
    lines = ['---']
    for key in ('group_id', 'part', 'section', 'passage_type', 'audio_asset',
                'subtitles', 'explanation_verbatim'):
        if key not in data:
            continue
        value = data[key]
        lines.append(f'{key}: ' + yaml_scalar(value))
    lines.append('questions:')
    for entry in data.get('questions', []):
        lines.append(f'  - id: {entry["id"]}')
        lines.append(f'    index: {entry["index"]}')
    if data.get('blanks'):
        lines.append('blanks:')
        for entry in data['blanks']:
            lines.append(f'  - index: {entry["index"]}')
            lines.append(f'    question_id: {entry["question_id"]}')
    lines.append('---')
    return '\n'.join(lines) + '\n'


def yaml_scalar(value: object) -> str:
    """Write a scalar the way the bank writes it, so files stay comparable."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if text == '' or re.search(r'[:#\[\]{}&*!|>\'"%@`]|^\s|\s$', text):
        return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return text


def referenced_assets(body: str) -> list[str]:
    """Asset ids the Markdown body points at, in first-seen order."""
    found: list[str] = []
    for match in re.finditer(r'/api/assets/([A-Za-z0-9_-]+)', body):
        asset = match.group(1)
        if asset not in found:
            found.append(asset)
    return found


def rewrite_asset_references(body: str, mapping: dict[str, str]) -> str:
    for old, new in mapping.items():
        body = body.replace('/api/assets/' + old, '/api/assets/' + new)
    return body


def rewrite_question_ids(body: str, mapping: dict[str, str]) -> str:
    for old, new in mapping.items():
        body = body.replace(old, new)
    return body


def register_assets(library_root: Path, asset_mapping: dict[str, str],
                    asset_payload: dict[str, bytes],
                    source_records: dict[str, dict]) -> None:
    """Add the renamed assets to the manifest so the bank can find them."""
    manifest_path = library_root / 'manifest.json'
    if not manifest_path.is_file():
        raise SystemExit('题库缺少 manifest.json，无法登记新资源')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assets = manifest.get('assets')
    if not isinstance(assets, list):
        raise SystemExit('题库 manifest 格式无效')
    known = {entry.get('id') for entry in assets if isinstance(entry, dict)}
    for old, new in asset_mapping.items():
        if new in known:
            continue
        is_audio = old.startswith('audio-')
        folder = 'audio' if is_audio else 'assets'
        suffix = '.flac' if is_audio else '.png'
        entry = {
            'id': new,
            'path': f'{folder}/{new}{suffix}',
            'media_type': 'audio/flac' if is_audio else 'image/png',
            'sha256': hashlib.sha256(asset_payload[old]).hexdigest(),
        }
        source = source_records.get(old) or {}
        if 'duration_seconds' in source:
            entry['duration_seconds'] = source['duration_seconds']
        assets.append(entry)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8')


def export_groups(library_root: Path, group_ids: list[str], out_dir: Path,
                  asset_root: Path | None = None) -> list[Path]:
    """Write one directory per group with its Markdown, media and pictures."""
    from toeic_practice.library import Library

    library = Library(library_root)
    library.load()
    if not library.available:
        raise SystemExit(f'题库无法加载：{library.load_error}')
    exam = library.exams.get('pool')
    if exam is None:
        raise SystemExit('未找到独立题库')
    wanted = set(group_ids)
    groups = [g for g in exam.groups if g['id'] in wanted]
    missing = wanted - {g['id'] for g in groups}
    if missing:
        raise SystemExit('题组不存在：' + ', '.join(sorted(missing)))
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for group in groups:
        source_md = library_root / 'parts' / f'part-{group["part"]}' / f'{group["id"]}.md'
        if not source_md.is_file():
            raise SystemExit(f'缺少题组 Markdown：{source_md}')
        text = source_md.read_text(encoding='utf-8')
        target = out_dir / group['id']
        target.mkdir(parents=True, exist_ok=True)
        (target / f'{group["id"]}.md').write_text(text, encoding='utf-8')
        written.append(target)
        for suffix in ('srt',):
            source = source_md.with_suffix('.' + suffix)
            if source.is_file():
                shutil.copy2(source, target / source.name)
        if group.get('audio'):
            asset_id = group['audio']['asset_id']
            asset = library.assets.get(asset_id)
            if asset:
                origin = library_root / asset['path']
                if origin.is_file():
                    shutil.copy2(origin, target / f'{group["id"]}.flac')
        for material in group.get('materials', []):
            asset_id = material.get('asset_id')
            if not asset_id:
                continue
            asset = library.assets.get(asset_id)
            if not asset:
                continue
            origin = library_root / asset['path']
            if origin.is_file():
                picture_dir = target / 'assets'
                picture_dir.mkdir(exist_ok=True)
                shutil.copy2(origin, picture_dir / origin.name)
    return written


def import_group(bundle: Path, library_root: Path, dry_run: bool = False) -> dict:
    """Copy one exported group into the bank under fresh identifiers."""
    from toeic_practice.library import Library
    from toeic_practice.md_pool import parse_md_group

    library = Library(library_root)
    library.load()
    if not library.available:
        raise SystemExit(f'题库无法加载：{library.load_error}')
    md_files = sorted(bundle.glob('*.md'))
    if len(md_files) != 1:
        raise SystemExit('导入目录必须恰好包含一个 Markdown 文件')
    md_file = md_files[0]
    text = md_file.read_text(encoding='utf-8')
    data, body = parse_frontmatter(text)
    try:
        # The running bank must accept the bundle before anything is written.
        parse_md_group(text, md_file.name)
    except ValueError as error:
        raise SystemExit(f'题组 Markdown 无法被题库读取：{error}') from error
    source_group = data.get('group_id')
    if not source_group or not GROUP_ID.match(str(source_group)):
        raise SystemExit('题组编号无效')
    questions = data.get('questions') or []
    if not questions:
        raise SystemExit('题组缺少题目列表')
    question_ids = []
    for entry in questions:
        qid = entry.get('id') if isinstance(entry, dict) else str(entry).split()[0]
        if not qid or not QUESTION_ID.match(str(qid)):
            raise SystemExit(f'题目条目无效：{entry}')
        question_ids.append(str(qid))
    new_group = new_group_id(str(source_group), text)
    mapping = {old: new_question_id(old, new_group) for old in question_ids}

    asset_mapping: dict[str, str] = {}
    asset_payload: dict[str, bytes] = {}
    # A recording is named by the frontmatter; a picture by the body.
    asset_ids = set(referenced_assets(body))
    if data.get('audio_asset'):
        asset_ids.add(str(data['audio_asset']))
    for asset in sorted(asset_ids):
        prefix = 'img' if asset.startswith('img-') else 'audio'
        payload = b''
        record = library.assets.get(asset)
        if record:
            origin = library_root / record['path']
            payload = origin.read_bytes() if origin.is_file() else b''
        if not payload:
            # A bundle carries its media under the source group id.
            candidates = [bundle / 'assets' / f'{asset}.png',
                          bundle / f'{source_group}.flac',
                          bundle / f'{asset}.flac']
            for candidate in candidates:
                if candidate.is_file():
                    payload = candidate.read_bytes()
                    break
        if not payload:
            raise SystemExit(f'资源文件缺失：{asset}')
        asset_payload[asset] = payload
        asset_mapping[asset] = new_asset_id(prefix, payload)

    blanks = data.get('blanks') or []
    new_blanks = []
    for entry in blanks:
        source_question = entry.get('question_id')
        if source_question not in mapping:
            raise SystemExit(f'空位条目引用了未知题目：{entry}')
        new_blanks.append({'index': entry.get('index'),
                           'question_id': mapping[source_question]})

    source_audio = data.get('audio_asset')
    audio_asset = None
    if source_audio:
        audio_asset = asset_mapping.get(str(source_audio))
        if not audio_asset:
            raise SystemExit(f'录音资源缺失：{source_audio}')
    source_subtitles = data.get('subtitles')
    subtitles = f'{new_group}.srt' if audio_asset else None

    new_body = rewrite_asset_references(rewrite_question_ids(body, mapping), asset_mapping)
    if source_subtitles:
        new_body = new_body.replace(str(source_subtitles), f'{new_group}.srt')
    new_text = frontmatter_lines({
        'group_id': new_group,
        'part': data.get('part'),
        'section': data.get('section'),
        'passage_type': data.get('passage_type'),
        'audio_asset': audio_asset,
        'subtitles': subtitles,
        'explanation_verbatim': data.get('explanation_verbatim'),
        'questions': [{'id': mapping[old], 'index': index + 1}
                      for index, old in enumerate(question_ids)],
        'blanks': new_blanks,
    }) + new_body

    part = int(data.get('part') or 0)
    if part < 1 or part > 7:
        raise SystemExit('Part 无效')
    target_dir = library_root / 'parts' / f'part-{part}'
    target_md = target_dir / f'{new_group}.md'
    if target_md.exists():
        # The identifier is derived from the content, so the very same
        # bundle may already sit in the bank. That is not a conflict.
        if target_md.read_text(encoding='utf-8') == new_text:
            return {'group_id': new_group, 'questions': len(question_ids),
                    'assets': len(asset_mapping), 'target': str(target_md),
                    'status': 'already-imported'}
        raise SystemExit('目标题组编号已被另一份内容占用')
    if dry_run:
        return {'group_id': new_group, 'questions': len(question_ids),
                'assets': len(asset_mapping), 'target': str(target_md)}
    target_dir.mkdir(parents=True, exist_ok=True)
    target_md.write_text(new_text, encoding='utf-8')
    if subtitles:
        source = bundle / str(source_subtitles)
        if not source.is_file():
            raise SystemExit(f'字幕文件缺失：{source_subtitles}')
        shutil.copy2(source, target_dir / subtitles)
    if audio_asset:
        source_audio = bundle / f'{source_group}.flac'
        if source_audio.is_file():
            target_audio = library_root / 'audio' / f'{audio_asset}.flac'
            target_audio.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_audio, target_audio)
    for material_asset, new_asset in asset_mapping.items():
        if not material_asset.startswith('img-'):
            continue
        target_asset_dir = library_root / 'assets'
        target_asset_dir.mkdir(parents=True, exist_ok=True)
        target_asset_dir.joinpath(f'{new_asset}.png').write_bytes(asset_payload[material_asset])
    register_assets(library_root, asset_mapping, asset_payload,
                     {key: (library.assets.get(key) or {})
                      for key in asset_mapping})
    return {'group_id': new_group, 'questions': len(question_ids),
            'assets': len(asset_mapping), 'target': str(target_md)}


def main() -> int:
    parser = argparse.ArgumentParser(description='导出或导入题组')
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export', help='导出指定题组')
    export.add_argument('--library', default=str(ROOT / 'content/question-pool'))
    export.add_argument('--out', required=True)
    export.add_argument('--group', action='append', default=[], help='题组编号，可重复')
    importer = sub.add_parser('import', help='导入一个题组目录')
    importer.add_argument('--library', default=str(ROOT / 'content/question-pool'))
    importer.add_argument('--bundle', required=True)
    importer.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.command == 'export':
        if not args.group:
            raise SystemExit('请至少指定一个题组编号')
        written = export_groups(Path(args.library), args.group, Path(args.out))
        print(json.dumps({'status': 'PASS', 'groups': [p.name for p in written]}, ensure_ascii=False))
    else:
        result = import_group(Path(args.bundle), Path(args.library), dry_run=args.dry_run)
        print(json.dumps({'status': 'PASS', **result}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

