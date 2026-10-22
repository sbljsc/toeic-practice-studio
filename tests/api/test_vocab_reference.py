"""The CC BY 4.0 word list enriches the causal vocabulary book."""
import json
from pathlib import Path

import pytest

from toeic_practice.vocab_reference import (
    VocabReference,
    load_vocab_reference,
    reference_entry,
)

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def reference() -> VocabReference:
    return load_vocab_reference(REPO)


def test_the_shipped_reference_loads_with_its_attribution(reference):
    assert reference.available
    assert len(reference.entries) > 1000
    source = reference.source
    assert source['license'] == 'CC BY 4.0'
    assert source['url'].startswith('https://')
    # CC BY requires that the credit travels with the material.
    assert 'CC BY 4.0' in source['attribution']
    assert source['url'] in source['attribution']


def test_every_entry_carries_a_definition_and_an_example(reference):
    for entry in reference.entries.values():
        assert entry['definition'], entry['word']
        assert entry['definition_simplified'], entry['word']
        assert entry['examples'], entry['word']


def test_a_lookup_is_case_insensitive(reference):
    exact = reference.get('Invoice')
    assert exact is not None
    assert exact['word'].lower() == 'invoice'
    assert reference.get('  INVOICE  ')['word'].lower() == 'invoice'


def test_the_simplified_definition_is_actually_simplified(reference):
    entry = reference.get('invoice')
    assert entry is not None
    # The source is traditional Chinese; the reader gets a simplified form.
    assert '發票' in entry['definition']
    assert '发票' in entry['definition_simplified']
    assert '發票' not in entry['definition_simplified']


def test_search_prefers_a_prefix_and_ranks_by_importance(reference):
    matches = reference.search('sched', 10)
    assert matches
    words = [m['word'].lower() for m in matches]
    assert 'schedule' in words
    # Every prefix match comes before a mere substring match.
    assert words.index('schedule') < len(words)


def test_an_unknown_word_is_not_invented(reference):
    assert reference.get('zzzqqqnotaword') is None
    assert reference.search('zzzqqqnotaword') == []


def test_the_reference_entry_carries_the_credit(reference):
    entry = reference_entry(reference, 'invoice')
    assert entry is not None
    assert entry['license'] == 'CC BY 4.0'
    assert entry['attribution']
    assert entry['source_url']


def test_a_missing_reference_file_is_not_fatal(tmp_path):
    empty = load_vocab_reference(tmp_path)
    assert not empty.available
    assert empty.get('invoice') is None


def test_a_broken_reference_file_is_not_fatal(tmp_path):
    (tmp_path / 'content' / 'vocabulary').mkdir(parents=True)
    (tmp_path / 'content' / 'vocabulary' / 'reference.json').write_text(
        '{not json', encoding='utf-8')
    empty = load_vocab_reference(tmp_path)
    assert not empty.available


def test_a_reference_with_an_unknown_schema_is_ignored(tmp_path):
    (tmp_path / 'content' / 'vocabulary').mkdir(parents=True)
    (tmp_path / 'content' / 'vocabulary' / 'reference.json').write_text(
        json.dumps({'schema_version': 99, 'entries': []}), encoding='utf-8')
    empty = load_vocab_reference(tmp_path)
    assert not empty.available


def test_the_http_endpoint_returns_the_entry_and_the_credit(client):
    response = client.get('/api/vocabulary/reference?q=invoice')
    assert response.status_code == 200
    body = response.json()
    assert body['exact']['word'].lower() == 'invoice'
    assert body['exact']['definition_simplified']
    assert body['source']['license'] == 'CC BY 4.0'
    assert body['source']['attribution']


def test_the_http_endpoint_searches_when_no_word_matches(client):
    response = client.get('/api/vocabulary/reference?q=sched')
    assert response.status_code == 200
    body = response.json()
    assert body['exact'] is None
    assert body['matches']
    assert all(match['license'] == 'CC BY 4.0' for match in body['matches'])


def test_the_http_endpoint_needs_a_query(client):
    response = client.get('/api/vocabulary/reference?q=')
    assert response.status_code == 400
    assert response.json()['code'] == 'missing_query'


def test_the_http_endpoint_does_not_invent_a_word(client):
    response = client.get('/api/vocabulary/reference?q=zzzqqqnotaword')
    assert response.status_code == 200
    body = response.json()
    assert body['exact'] is None
    assert body['matches'] == []
