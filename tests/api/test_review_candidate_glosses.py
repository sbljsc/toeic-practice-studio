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
