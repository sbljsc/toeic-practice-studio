"""Build the vocabulary reference file from the CC BY 4.0 TOEIC word list.

The upstream dataset is a JSON tree of entries, each with a Chinese
definition, a star rating, a business category, parts of speech, word forms
and bilingual examples. The application needs a small, read-only lookup keyed
by the lowercase English word, so this tool reduces the source to the fields
the vocabulary book actually shows and writes one compact JSON file.

The source is in traditional Chinese while the reader writes simplified
Chinese, so both readings are kept: the source text and a simplified form.

The dataset is licensed under CC BY 4.0, which allows redistribution and
adaptation and requires attribution. The attribution is written into the
output file itself and repeated in the repository notices.

`zhconv` is a build-time tool only. The application reads the generated JSON
and never needs the converter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'content' / 'vocabulary' / 'reference.json'

# The upstream work, named exactly so the notice can point at it.
SOURCE_NAME = '完整 TOEIC 單字庫 (English–Traditional Chinese)'
SOURCE_URL = 'https://huggingface.co/datasets/LEE-WHITE/toeic-vocab-tw'
LICENSE = 'CC BY 4.0'
LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/'


def to_simplified(text: str) -> str:
    """Convert traditional Chinese to simplified, leaving other text alone."""
    if not text:
        return ''
    try:
        import zhconv
    except ImportError as error:  # pragma: no cover - build tool dependency
        raise SystemExit(
            '构建词汇参考需要 zhconv：pip install zhconv') from error
    return zhconv.convert(text, 'zh-cn')


def collect_entries(source: dict) -> list[dict]:
    """Reduce the source tree to the fields the vocabulary book shows."""
    entries: dict[str, dict] = {}
    groups = source.get('vocabulary_by_importance')
    if not isinstance(groups, dict):
        raise ValueError('source has no vocabulary_by_importance tree')
    for group in groups.values():
        for item in group:
            word = str(item.get('english_word', '')).strip()
            if not word:
                continue
            definition = str(item.get('chinese_definition', '')).strip()
            examples = []
            for example in (item.get('examples') or [])[:2]:
                english = str(example.get('english', '')).strip()
                chinese = str(example.get('chinese', '')).strip()
                if english:
                    examples.append({'en': english, 'zh': chinese,
                                     'zh_simplified': to_simplified(chinese)})
            record = {
                'word': word,
                'definition': definition,
                'definition_simplified': to_simplified(definition),
                'star': int(item.get('star_rating') or 0),
                'category': str(item.get('category', '')).strip(),
                'parts_of_speech': [str(p) for p in (item.get('parts_of_speech') or [])],
                'examples': examples,
            }
            key = word.lower()
            existing = entries.get(key)
            if existing is None:
                # The source leaves about a third of its rows without a
                # definition or an example, mostly one-star words and
                # sentence patterns. A row with neither carries nothing to
                # show, so it is not worth shipping.
                if record['definition'] or record['examples']:
                    entries[key] = record
                continue
            # The source repeats a word under different star ratings. Keep the
            # richest record and the best rating.
            if record['star'] > existing['star']:
                existing['star'] = record['star']
            if len(record['examples']) > len(existing['examples']):
                existing['examples'] = record['examples']
            if len(record['definition']) > len(existing['definition']):
                existing['definition'] = record['definition']
                existing['definition_simplified'] = record['definition_simplified']
    return [entries[key] for key in sorted(entries)]


def build(source_path: Path, output_path: Path) -> dict:
    source = json.loads(source_path.read_text(encoding='utf-8'))
    entries = collect_entries(source)
    if not entries:
        raise ValueError('no vocabulary entries were read from the source')
    metadata = source.get('metadata') or {}
    document = {
        'schema_version': 1,
        'source': {
            'name': SOURCE_NAME,
            'url': SOURCE_URL,
            'license': LICENSE,
            'license_url': LICENSE_URL,
            'attribution': (
                f'"{SOURCE_NAME}" is licensed under CC BY 4.0. '
                f'Copyright by the dataset authors. Source: {SOURCE_URL}. '
                f'Changes: Chinese text is also provided in simplified form and '
                f'two examples per word are kept.'
            ),
            'upstream_version': str(metadata.get('version', '')),
            'upstream_words': metadata.get('total_words'),
        },
        'entries': entries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, ensure_ascii=False,
                                     separators=(',', ':')) + '\n', encoding='utf-8')
    return {
        'entries': len(entries),
        'bytes': output_path.stat().st_size,
        'sha256': hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='上游 toeic_vocabulary_raw.json')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    stats = build(args.source, args.out)
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

