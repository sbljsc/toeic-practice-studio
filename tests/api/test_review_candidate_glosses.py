"""A candidate word in the review shows its meaning without a second page."""
from pathlib import Path

from toeic_practice.vocab_reference import load_vocab_reference

from test_vocabulary import _closed_wrong_attempt

REPO = Path(__file__).resolve().parents[2]


def test_a_candidate_carries_its_meaning_and_an_example(client):
    """A candidate the reference knows arrives with its gloss attached."""
    attempt = _closed_wrong_attempt(client)
    qid = attempt["questions"][0]["id"]
    body = client.get(f"/api/attempts/{attempt['id']}/candidates/{qid}").json()
    assert body["candidates"]
    # The fixture stem mentions "question", which the word list knows.
    candidate = next(c for c in body["candidates"] if c["term"] == "question")
    reference = candidate["reference"]
    assert reference is not None
    assert reference["definition_simplified"]
    assert reference["examples"]
    assert reference["examples"][0]["en"]
    assert reference["license"] == "CC BY 4.0"
    assert reference["attribution"]


def test_a_candidate_the_reference_does_not_know_stays_usable(client):
    """An unknown word still comes back, simply without a gloss."""
    attempt = _closed_wrong_attempt(client)
    qid = attempt["questions"][0]["id"]
    body = client.get(f"/api/attempts/{attempt['id']}/candidates/{qid}").json()
    unknown = next(c for c in body["candidates"] if c["term"] == "keywordalpha")
    assert unknown["reference"] is None
    assert unknown["term"]


def test_the_candidates_still_never_confirm_a_word(client):
    """Showing a meaning must not turn a candidate into confirmed evidence."""
    attempt = _closed_wrong_attempt(client)
    qid = attempt["questions"][0]["id"]
    client.get(f"/api/attempts/{attempt['id']}/candidates/{qid}")
    assert client.get("/api/vocabulary").json()["entries"] == []


def test_the_reference_used_by_the_candidates_matches_the_shipped_file(client):
    """The glosses come from the same file the vocabulary book uses."""
    shipped = load_vocab_reference(REPO)
    attempt = _closed_wrong_attempt(client)
    qid = attempt["questions"][0]["id"]
    body = client.get(f"/api/attempts/{attempt['id']}/candidates/{qid}").json()
    candidate = next(c for c in body["candidates"] if c["term"] == "question")
    expected = shipped.get("question")["definition_simplified"]
    assert candidate["reference"]["definition_simplified"] == expected


def test_a_confirmed_word_without_a_sense_gets_one_from_the_word_list(client):
    """Confirming a word the list knows fills in its meaning."""
    attempt = _closed_wrong_attempt(client)
    qid = attempt["questions"][0]["id"]
    response = client.put(f"/api/attempts/{attempt['id']}/reviews/{qid}", json={
        "causes": ["meaning"],
        "words": [{"term": "invoice", "sense": "", "modality": "meaning", "causal": True}],
    }, headers={"X-Tab-ID": "tab-gloss", "Origin": "http://testserver"})
    assert response.status_code == 200
    entries = client.get("/api/vocabulary").json()["entries"]
    entry = next(e for e in entries if e["term"] == "invoice")
    assert entry["sense"]
    assert entry["reference"] is not None
    assert entry["sense"] == entry["reference"]["definition_simplified"]


def test_a_word_the_list_does_not_know_keeps_the_sense_it_was_given(client):
    """An unknown word is never given a meaning it did not have."""
    attempt = _closed_wrong_attempt(client)
    qid = attempt["questions"][0]["id"]
    client.put(f"/api/attempts/{attempt['id']}/reviews/{qid}", json={
        "causes": ["meaning"],
        "words": [{"term": "zzznotaword", "sense": "我自己写的意思",
                   "modality": "meaning", "causal": True}],
    }, headers={"X-Tab-ID": "tab-gloss", "Origin": "http://testserver"})
    entries = client.get("/api/vocabulary").json()["entries"]
    entry = next(e for e in entries if e["term"] == "zzznotaword")
    assert entry["sense"] == "我自己写的意思"
    assert entry["reference"] is None


def test_a_sense_the_learner_wrote_is_never_overwritten(client):
    """The learner's own wording wins over the word list."""
    attempt = _closed_wrong_attempt(client)
    qid = attempt["questions"][0]["id"]
    client.put(f"/api/attempts/{attempt['id']}/reviews/{qid}", json={
        "causes": ["meaning"],
        "words": [{"term": "invoice", "sense": "我自己的理解",
                   "modality": "meaning", "causal": True}],
    }, headers={"X-Tab-ID": "tab-gloss", "Origin": "http://testserver"})
    entries = client.get("/api/vocabulary").json()["entries"]
    entry = next(e for e in entries if e["term"] == "invoice")
    assert entry["sense"] == "我自己的理解"
