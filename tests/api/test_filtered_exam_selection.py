"""Fixed exams stay complete; filtered Part exams play only selected clips."""
import json
import uuid

import pytest

from test_attempts import create, hdr, start
from test_custom_cross_exam_selection import multi_exam_client
from test_custom_exam_phases import custom_exam_client


def seed_filtered_part(client, *, mixed=False, unanswered=False):
    a = start(client, create(client, parts=[1, 5] if mixed else [1]))
    selected = ["t01-q006"] + (["t01-q101"] if mixed else [])
    questions = client.app.state.services.library.exams["test-01"].questions
    wrong = {q["id"]: next(o["id"] for o in q["options"] if o["id"] != q["answer"]) for q in questions if q["id"] in selected}
    answers = [(f"t01-q{n:03d}", "A") for n in range(1, 6)] if unanswered else [(qid, wrong[qid]) for qid in selected]
    for qid, option in answers:
        response = client.put(f"/api/attempts/{a['id']}/answers/{qid}", headers=hdr(),
            json={"option_id": option, "flagged": True, "revision": 0, "mutation_id": str(uuid.uuid4())})
        assert response.status_code == 200, response.text
    assert client.post(f"/api/attempts/{a['id']}/submit", headers=hdr(), json={}).status_code == 200
    return selected


@pytest.mark.parametrize("kind", ["countdown", "countup", "none"])
@pytest.mark.parametrize("question_filter", ["wrong", "bookmarked"])
@pytest.mark.parametrize("mixed", [False, True])
def test_filtered_part_exam_plays_late_exact_group_with_personal_timer(custom_exam_client, clock, kind, question_filter, mixed):
    client = custom_exam_client
    selected = seed_filtered_part(client, mixed=mixed)
    response = client.post("/api/attempts", headers=hdr(), json={"exam_ids": ["test-01"],
        "scope": "part", "parts": [1, 5] if mixed else [1], "mode": "exam",
        "question_filter": question_filter, "timer": {"kind": kind, "duration_seconds": 120}})
    assert response.status_code == 200, response.text
    a = response.json()
    assert [q["id"] for q in a["questions"]] == selected
    assert len(a["audio_queue"]) == 1
    clip = a["audio_queue"][0]
    assert (clip["start_seconds"], clip["end_seconds"]) == (22, 25)
    assert clip["question_ids"] == ["t01-q006"]
    running = start(client, a)
    assert running["timing"]["kind"] == kind and not running["timing"]["can_pause"]
    assert running["timing"]["phase_question_ids"] == selected
    for qid in selected:
        saved = client.put(f"/api/attempts/{a['id']}/answers/{qid}", headers=hdr(),
            json={"option_id": "A", "revision": 0, "mutation_id": str(uuid.uuid4())})
        assert saved.status_code == 200, saved.text
    assert client.post(f"/api/attempts/{a['id']}/pause", headers=hdr(), json={}).status_code == 409
    clock.advance(4)
    for path in (f"/api/attempts/{a['id']}", f"/api/attempts/{a['id']}/clock"):
        state = client.get(path).json()
        assert state["timing"]["elapsed_ms"] == state["audio_elapsed_ms"] == 4000
        assert state["timing"]["remaining_ms"] == (116000 if kind == "countdown" else None)
    clock.advance(116)
    assert client.get(f"/api/attempts/{a['id']}/clock").json()["status"] == ("expired" if kind == "countdown" else "running")


def test_unanswered_part_exam_also_uses_exact_selected_group(custom_exam_client):
    client = custom_exam_client
    seed_filtered_part(client, unanswered=True)
    a = create(client, parts=[1], mode="exam", question_filter="unanswered")
    assert [q["id"] for q in a["questions"]] == ["t01-q006"]
    assert [(item["start_seconds"], item["end_seconds"]) for item in a["audio_queue"]] == [(22, 25)]


def test_filtered_part_missing_group_cue_never_falls_back_to_part(custom_exam_client, library_root):
    client = custom_exam_client
    seed_filtered_part(client)
    path = library_root / "audio-cues.json"
    cues = json.loads(path.read_text())
    cues["exams"]["test-01"]["groups"] = []
    path.write_text(json.dumps(cues), encoding="utf-8")
    client.app.state.services.library.load()
    response = client.post("/api/attempts", headers=hdr(), json={"exam_ids": ["test-01"],
        "scope": "part", "parts": [1], "mode": "exam", "question_filter": "wrong", "timer": {"kind": "none"}})
    assert response.status_code == 409 and response.json()["code"] == "cues_not_ready"


@pytest.mark.parametrize("scope", ["full", "listening", "reading"])
@pytest.mark.parametrize("question_filter", ["wrong", "bookmarked", "unanswered"])
def test_fixed_exam_rejects_partial_filter_with_explanation(client, scope, question_filter):
    response = client.post("/api/attempts", headers=hdr(), json={"exam_ids": ["test-01"],
        "scope": scope, "mode": "exam", "question_filter": question_filter, "timer": {"kind": "none"}})
    assert response.status_code == 400, response.text[:200]
    assert response.json()["code"] == "exam_requires_all_questions"
    assert "专项" in response.json()["detail"] and "练习" in response.json()["detail"]
    assert client.app.state.services.store.query_one("SELECT COUNT(*) AS n FROM attempts")["n"] == 0


@pytest.mark.parametrize("scope", ["full", "listening", "reading", "part", "custom"])
def test_practice_keeps_filters_for_every_scope(custom_exam_client, scope):
    client = custom_exam_client
    seed_filtered_part(client, mixed=True)
    a = create(client, scope=scope, parts=[1, 5], mode="practice", question_filter="wrong",
               group_ids=["t01-p1-q6", "t01-p5-q101"])
    assert {q["id"] for q in a["questions"]} == ({"t01-q101"} if scope == "reading" else
        {"t01-q006"} if scope == "listening" else {"t01-q006", "t01-q101"})
