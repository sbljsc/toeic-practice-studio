"""Export and import question groups as plain, readable Markdown bundles.

An exported group is one directory that holds the group's Markdown file, the
matching subtitle file, the recording, and any picture the group references.
Importing assigns fresh identifiers so that a bundle can never collide with
the running bank: the new group id is derived from the source group id and
the Markdown content, and each new question id from the source question id
and the new group id.
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
    if not text.startswith('---\n'):
        raise ValueError('缺少 frontmatter')
    end = text.find('\n---\n', 3)
    if end < 0:
        raise ValueError('frontmatter 未闭合')
    block = text[4:end]
    body = text[end + 5:]
    data: dict = {}
    key = None
    for line in block.split('\n'):
        if not line.strip():
            continue
        if line.startswith('  - ') and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(line[4:].strip())
            continue
        if line.startswith('  ') and key:
            if isinstance(data.get(key), list) and data[key]:
                data[key][-1] = data[key][-1] + ' ' + line.strip()
            continue
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()
        if value == '':
            data[key] = []
        elif value == 'null':
            data[key] = None
        elif value.startswith('[') and value.endswith(']'):
            data[key] = [item.strip() for item in value[1:-1].split(',') if item.strip()]
        else:
            data[key] = value
    return data, body


def frontmatter_lines(data: dict) -> str:
    """Serialize the frontmatter block this tool understands."""
    lines = ['---']
    for key in ('group_id', 'part', 'section', 'passage_type', 'audio', 'subtitles'):
        if key not in data:
            continue
        value = data[key]
        lines.append(f'{key}: ' + ('null' if value is None else str(value)))
    lines.append('questions:')
    for entry in data.get('questions', []):
        lines.append(f'  - {entry}')
    if data.get('blanks'):
        lines.append('blanks:')
        for entry in data['blanks']:
            lines.append(f'  - {entry}')
    lines.append('---')
    return '\n'.join(lines) + '\n'


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
    source_group = data.get('group_id')
    if not source_group or not GROUP_ID.match(str(source_group)):
        raise SystemExit('题组编号无效')
    questions = data.get('questions') or []
    if not questions:
        raise SystemExit('题组缺少题目列表')
    question_ids = []
    for entry in questions:
        parts = str(entry).split()
        if len(parts) != 2 or not QUESTION_ID.match(parts[0]):
            raise SystemExit(f'题目条目无效：{entry}')
        question_ids.append(parts[0])
    new_group = new_group_id(str(source_group), text)
    mapping = {old: new_question_id(old, new_group) for old in question_ids}
    new_body = rewrite_question_ids(body, mapping)

    asset_mapping: dict[str, str] = {}
    for asset in referenced_assets(body):
        prefix = 'img' if asset.startswith('img-') else 'audio'
        record = library.assets.get(asset)
        if record:
            origin = library_root / record['path']
            payload = origin.read_bytes() if origin.is_file() else b''
        else:
            local = bundle / 'assets' / f'{asset}.png'
            payload = local.read_bytes() if local.is_file() else b''
        asset_mapping[asset] = new_asset_id(prefix, payload)
    new_body = rewrite_asset_references(new_body, asset_mapping)

    new_text = frontmatter_lines({
        'group_id': new_group,
        'part': data.get('part'),
        'section': data.get('section'),
        'passage_type': data.get('passage_type'),
        'audio': data.get('audio'),
        'subtitles': data.get('subtitles'),
        'questions': [f'{mapping[old]} {index + 1}' for index, old in enumerate(question_ids)],
        'blanks': data.get('blanks'),
    }) + new_body

    part = int(data.get('part') or 0)
    if part < 1 or part > 7:
        raise SystemExit('Part 无效')
    target_dir = library_root / 'parts' / f'part-{part}'
    target_md = target_dir / f'{new_group}.md'
    if target_md.exists():
        raise SystemExit('目标题组已存在')
    if dry_run:
        return {'group_id': new_group, 'questions': len(question_ids),
                'assets': len(asset_mapping), 'target': str(target_md)}
    target_dir.mkdir(parents=True, exist_ok=True)
    target_md.write_text(new_text, encoding='utf-8')
    for suffix in ('srt',):
        source = bundle / md_file.with_suffix('.' + suffix).name
        if source.is_file():
            shutil.copy2(source, target_dir / f'{new_group}.{suffix}')
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

