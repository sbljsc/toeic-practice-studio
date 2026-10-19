"""Validate the standalone bank and its distribution boundary without writes."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/src'))
from toeic_practice.library import Library


def main():
    root = ROOT / 'content/question-pool'
    library = Library(root)
    library.load()
    assert library.available and library.pool_mode, library.load_error
    pool = library.exams['pool']
    assert len(pool.questions) == 2000 and len(pool.groups) == 1030
    assert [sum(q['part'] == p for q in pool.questions) for p in range(1, 8)] == [60,250,390,300,300,160,540]
    assert sum(bool(g.get('audio')) for g in pool.groups) == 540
    assert sum(len(g.get('listening_script', {}).get('sentences', [])) for g in pool.groups) == 3408
    content = json.loads((root / 'pool.json').read_text(encoding='utf-8'))
    branding = r'\u65b0\u4e1c\u65b9|new[ -]?oriental|noe' + '2019'
    forbidden = branding + r'|source_exam|source_question|test-\d\d|(?:^|\s)[A-Z]:[\\/]'
    def clean(value):
        if isinstance(value,str):
            assert not re.search(forbidden,value,re.I), 'private source metadata in bank'
        elif isinstance(value,dict):
            for key,item in value.items():
                clean(key);clean(item)
        elif isinstance(value,list):
            for item in value:clean(item)
    clean(content)
    ignored = {'.git','.venv','node_modules','.data','dist','__pycache__','.pytest_cache'}
    for path in ROOT.rglob('*'):
        if not path.is_file() or any(part in ignored or part.startswith('.venv-') for part in path.relative_to(ROOT).parts):
            continue
        assert not path.is_symlink(), 'linked source file is not portable'
        assert path.suffix.lower() not in {'.pdf','.docx','.sqlite3','.db','.bak'}, 'private source or learner artifact in payload'
        if path.suffix.lower() in {'.py','.ts','.tsx','.md','.json','.html','.txt','.cmd'}:
            text = path.read_text(encoding='utf-8')
            assert not re.search(branding,text,re.I), 'source branding in ' + path.relative_to(ROOT).as_posix()
            assert not re.search(r'(?:[A-Z]:\\(?:Users|Project)\\|[A-Z]:/(?:Users|Project)/)',text,re.I), 'private absolute path in payload'
    for q in pool.questions:
        assert not q.get('source_pages') and not q['explanation'].get('source_pages')
    for g in pool.groups:
        assert not g.get('source_pages') and not g.get('listening_script', {}).get('source_pages')
    expected = {'manifest.json', 'pool.json'} | {a['path'] for a in library.assets.values()}
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    assert actual == expected, 'missing or extra content file'
    assert not any(p.is_symlink() for p in root.rglob('*')), 'linked content is not portable'
    assert max((root / p).stat().st_size for p in actual) < 95 * 1024 * 1024, 'file exceeds normal Git size budget'
    print(json.dumps({'status':'PASS', 'questions':len(pool.questions), 'groups':len(pool.groups),
        'audio_clips':540, 'sentences':3408, 'registered_files':len(actual),
        'library_version':library.library_version()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
