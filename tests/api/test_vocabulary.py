"""Vocabulary causality, threshold, retraction, mastery cycle tests."""
import uuid

import pytest

TAB = "tab-vocab"


def hdr():
    return {"X-Tab-ID": TAB, "Origin": "http://testserver"}


def _closed_wrong_attempt(client, part=5, count=1):
    """Create a practice attempt, answer `count` questions wrong, submit."""
    attempt = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "part", "parts": [part],
        "mode": "practice", "timer": {"kind": "none"}, "question_filter": "all"},
        headers=hdr()).json()
    client.post(f"/api/attempts/{attempt['id']}/claim",
                json={"takeover": False}, headers=hdr())
    client.post(f"/api/attempts/{attempt['id']}/start",
                json={"media_ready": True}, headers=hdr())
    for q in attempt["questions"][:count]:
        # fixture key: "ABCD"[(number - part_lo) % 4]; part 5 starts at 101,
        # part 6 at 131. Pick any option that is not the key.
        part_lo = 101 if part == 5 else 131
        correct = "ABCD"[(q["number"] - part_lo) % 4]
        wrong = next(o for o in ("B", "C", "D", "A") if o != correct)
        client.put(f"/api/attempts/{attempt['id']}/answers/{q['id']}",
                   json={"option_id": wrong, "revision": 0,
                         "mutation_id": str(uuid.uuid4())}, headers=hdr())
    client.post(f"/api/attempts/{attempt['id']}/submit", json={}, headers=hdr())
    return attempt


def _review(client, attempt_id, qid, words):
    return client.put(f"/api/attempts/{attempt_id}/reviews/{qid}",
                      json={"causes": ["meaning"], "words": words}, headers=hdr())


def _word(term, sense="", modality="meaning", causal=True):
    return {"term": term, "sense": sense, "modality": modality, "causal": causal}


def test_candidates_never_auto_confirm(client):
    attempt = _closed_wrong_attempt(client)
    qid = attempt["questions"][0]["id"]
    candidates = client.get(f"/api/attempts/{attempt['id']}/candidates/{qid}").json()
    assert candidates["candidates"]
    assert client.get("/api/vocabulary").json()["entries"] == []


def test_explicit_confirmation_builds_evidence(client):
    attempt = _closed_wrong_attempt(client, count=1)
    qid = attempt["questions"][0]["id"]
    resp = _review(client, attempt["id"], qid, [_word("keywordalpha")])
    assert resp.status_code == 200
    entries = client.get("/api/vocabulary").json()["entries"]
    entry = next(e for e in entries if e["term"] == "keywordalpha")
    assert entry["question_count"] == 1
    assert entry["status"] == "candidate"


def test_threshold_needs_distinct_questions_and_two_groups(client):
    # Three wrong questions in the same single-question groups (part 5):
    # distinct questions but distinct groups (each p5 group has 1 question).
    attempt = _closed_wrong_attempt(client, count=3)
    for q in attempt["questions"][:3]:
        _review(client, attempt["id"], q["id"], [_word("sharedterm")])
    entries = client.get("/api/vocabulary").json()["entries"]
    entry = next(e for e in entries if e["term"] == "sharedterm")
    assert entry["question_count"] == 3
    assert entry["material_count"] == 3
    assert entry["status"] == "must_learn"


def test_same_question_repeat_counts_once(client):
    attempt = _closed_wrong_attempt(client, count=1)
    qid = attempt["questions"][0]["id"]
    _review(client, attempt["id"], qid, [_word("repeatterm")])
    _review(client, attempt["id"], qid, [_word("repeatterm")])
    _review(client, attempt["id"], qid, [_word("repeatterm")])
    entries = client.get("/api/vocabulary").json()["entries"]
    entry = next(e for e in entries if e["term"] == "repeatterm")
    assert entry["question_count"] == 1


def test_retraction_removes_evidence(client):
    attempt = _closed_wrong_attempt(client, count=3)
    for q in attempt["questions"][:3]:
        _review(client, attempt["id"], q["id"], [_word("retractterm")])
    before = next(e for e in client.get("/api/vocabulary").json()["entries"]
                  if e["term"] == "retractterm")
    assert before["question_count"] == 3
    # retract the first question's evidence with empty words
    _review(client, attempt["id"], attempt["questions"][0]["id"], [])
    after = next(e for e in client.get("/api/vocabulary").json()["entries"]
                 if e["term"] == "retractterm")
    assert after["question_count"] == 2


def test_review_rejected_on_correct_or_open(client):
    attempt = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "part", "parts": [5],
        "mode": "practice", "timer": {"kind": "none"}, "question_filter": "all"},
        headers=hdr()).json()
    qid = attempt["questions"][0]["id"]
    open_review = _review(client, attempt["id"], qid, [_word("x")])
    assert open_review.status_code == 409
    client.post(f"/api/attempts/{attempt['id']}/claim", json={"takeover": False}, headers=hdr())
    client.post(f"/api/attempts/{attempt['id']}/start", json={"media_ready": True}, headers=hdr())
    client.put(f"/api/attempts/{attempt['id']}/answers/{qid}",
               json={"option_id": "A", "revision": 0, "mutation_id": str(uuid.uuid4())},
               headers=hdr())
    client.post(f"/api/attempts/{attempt['id']}/submit", json={}, headers=hdr())
    correct_review = _review(client, attempt["id"], qid, [_word("x")])
    assert correct_review.status_code == 409


def test_mastered_cycle_restarts_evidence(client):
    attempt = _closed_wrong_attempt(client, count=3)
    for q in attempt["questions"][:3]:
        _review(client, attempt["id"], q["id"], [_word("cycleterm")])
    entry = next(e for e in client.get("/api/vocabulary").json()["entries"]
                 if e["term"] == "cycleterm")
    assert entry["status"] == "must_learn"
    patched = client.patch(f"/api/vocabulary/{entry['id']}",
                           json={"mastered": True}, headers=hdr())
    entry = next(e for e in patched.json()["entries"] if e["term"] == "cycleterm")
    assert entry["status"] == "mastered"
    # unmaster: a fresh cycle starts, old evidence stays but is out of cycle
    patched = client.patch(f"/api/vocabulary/{entry['id']}",
                           json={"mastered": False}, headers=hdr())
    entry = next(e for e in patched.json()["entries"] if e["term"] == "cycleterm")
    assert entry["status"] == "candidate"
    assert entry["question_count"] == 0  # current cycle is empty
    assert entry["lifetime_question_count"] == 3


def test_manual_required_promotes_concentrated(client):
    attempt = _closed_wrong_attempt(client, count=1)
    qid = attempt["questions"][0]["id"]
    _review(client, attempt["id"], qid, [_word("manualterm")])
    entry = next(e for e in client.get("/api/vocabulary").json()["entries"]
                 if e["term"] == "manualterm")
    assert entry["status"] == "candidate"
    patched = client.patch(f"/api/vocabulary/{entry['id']}",
                           json={"manual_required": True}, headers=hdr())
    entry = next(e for e in patched.json()["entries"] if e["term"] == "manualterm")
    assert entry["status"] == "must_learn"


def test_concentrated_is_threshold_in_one_material(client):
    # Part 6 fixture groups hold 3 questions on one shared material; answering
    # all three wrong and tagging the same word gives 3 questions / 1 group.
    attempt = _closed_wrong_attempt(client, part=6, count=3)
    for q in attempt["questions"][:3]:
        _review(client, attempt["id"], q["id"], [_word("denseword")])
    entry = next(e for e in client.get("/api/vocabulary").json()["entries"]
                 if e["term"] == "denseword")
    assert entry["question_count"] == 3
    assert entry["material_count"] == 1
    assert entry["status"] == "concentrated"


def test_settings_threshold_validation(client):
    ok = client.patch("/api/settings", json={"vocabulary_threshold": 5}, headers=hdr())
    assert ok.status_code == 200
    assert client.get("/api/settings").json()["vocabulary_threshold"] == 5
    bad = client.patch("/api/settings", json={"vocabulary_threshold": 99}, headers=hdr())
    assert bad.status_code == 400
    zero = client.patch("/api/settings", json={"vocabulary_threshold": 0}, headers=hdr())
    assert zero.status_code == 400
