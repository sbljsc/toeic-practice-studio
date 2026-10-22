"""Read-only word reference that enriches the causal vocabulary book.

The vocabulary book records what the learner actually got wrong. This
module adds the reference material for those words and for words the
learner is about to look up: a Chinese definition, a business category,
the parts of speech, and bilingual example sentences.

The reference data is the TOEIC word list published under CC BY 4.0. The
file carries its own attribution, which the API hands to the browser so
the credit travels with the content.
"""
from __future__ import annotations

import json
from pathlib import Path


class VocabReference:
    """A lookup from an English word to its reference entry."""

    def __init__(self, entries: dict[str, dict], source: dict) -> None:
        self.entries = entries
        self.source = source

    @property
    def available(self) -> bool:
        return bool(self.entries)

    def get(self, term: str) -> dict | None:
        """Find one word. A single word wins over a longer phrase."""
        key = (term or '').strip().lower()
        if not key:
            return None
        return self.entries.get(key)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Find words whose name starts with, or contains, the query."""
        key = (query or '').strip().lower()
        if not key:
            return []
        starts: list[dict] = []
        contains: list[dict] = []
        for term, entry in self.entries.items():
            if term.startswith(key):
                starts.append(entry)
            elif key in term:
                contains.append(entry)
        starts.sort(key=lambda e: (-e.get('star', 0), e['word']))
        contains.sort(key=lambda e: (-e.get('star', 0), e['word']))
        return (starts + contains)[:max(1, limit)]


def load_vocab_reference(root: Path) -> VocabReference:
    """Read the reference file. A missing or broken file is not fatal."""
    path = Path(root) / 'content' / 'vocabulary' / 'reference.json'
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return VocabReference({}, {})
    if not isinstance(document, dict) or document.get('schema_version') != 1:
        return VocabReference({}, {})
    raw_entries = document.get('entries')
    if not isinstance(raw_entries, list):
        return VocabReference({}, {})
    entries: dict[str, dict] = {}
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        word = str(item.get('word', '')).strip()
        if not word:
            continue
        entries[word.lower()] = {
            'word': word,
            'definition': str(item.get('definition', '')),
            'definition_simplified': str(item.get('definition_simplified', '')),
            'star': int(item.get('star') or 0),
            'category': str(item.get('category', '')),
            'parts_of_speech': list(item.get('parts_of_speech') or []),
            'examples': list(item.get('examples') or []),
        }
    source = document.get('source') if isinstance(document.get('source'), dict) else {}
    return VocabReference(entries, source)


def reference_entry(reference: VocabReference, term: str) -> dict | None:
    """Shape one entry for the browser, with the attribution attached."""
    entry = reference.get(term)
    if entry is None:
        return None
    result = dict(entry)
    result['attribution'] = reference.source.get('attribution', '')
    result['source_url'] = reference.source.get('url', '')
    result['license'] = reference.source.get('license', '')
    return result

