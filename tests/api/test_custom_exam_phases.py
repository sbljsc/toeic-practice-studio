"""Exact-scope exam retakes must expose a playable authoritative audio phase."""
import json
import uuid

import pytest

from test_attempts import answer, create, hdr, start
from test_custom_cross_exam_selection import multi_exam_client


@pytest.fixture
def custom_exam_client(multi_exam_client, library_root):
    path = library_root / "audio-cues.json"
    data = json.loads(path.read_text())
    for exam in data["exams"].values():
        exam["groups"] += [
            {"part": 1, "first_question": n, "last_question": n,
             "start_seconds": 2 + (n - 1) * 4, "end_seconds": 5 + (n - 1) * 4,
             "verified": True} for n in range(1, 7)]
    path.write_text(json.dumps(data), encoding="utf-8")
    multi_exam_client.app.state.services.library.load()
    return multi_exam_client


def custom_exam(client, group_ids, *, exam_ids=None, seconds=120, kind="countdown"):
    return client.post("/api/attempts", headers=hdr(), json={
        "exam_ids": exam_ids or ["test-01"], "scope": "custom", "mode": "exam",
        "group_ids": group_ids, "question_filter": "all",
        "timer": {"kind": kind, "duration_seconds": seconds}})


def test_filtered_part1_exam_exact_group_retake_is_strict_and_timed(custom_exam_client, clock):
    client = custom_exam_client
    seed = start(client, create(client, parts=[1]))
    assert answer(client, seed, "t01-q001", "B").status_code == 200
    client.post(f"/api/attempts/{seed['id']}/submit", headers=hdr(), json={})
    filtered = start(client, create(client, parts=[1], mode="exam", question_filter="wrong",
        timer={"kind": "countdown", "duration_seconds": 120}))
    source = client.post(f"/api/attempts/{filtered['id']}/submit", headers=hdr(), json={}).json()
    response = custom_exam(client, [g["id"] for g in source["groups"]])
    assert response.status_code == 200, response.text
    a = response.json()
    assert a["mode"] == "exam" and a["timing"]["phase"] == "listening"
    assert [q["id"] for q in a["questions"]] == [q["id"] for q in source["questions"]] == ["t01-q001"]
    assert a["timing"]["phase_question_ids"] == ["t01-q001"]
    assert len(a["audio_queue"]) == 1
    assert (a["audio_queue"][0]["start_seconds"], a["audio_queue"][0]["end_seconds"]) == (2, 5)
    assert a["audio_queue"][0]["question_ids"] == ["t01-q001"]
    blocked = client.post(f"/api/attempts/{a['id']}/start", headers=hdr(), json={"media_ready": False})
    assert blocked.status_code == 409 and client.get(f"/api/attempts/{a['id']}").json()["status"] == "ready"
    started = start(client, a)
    deadline = started["timing"]["deadline_at_ms"]
    assert started["timing"]["remaining_ms"] == 120000 and not started["timing"]["can_pause"]
    assert client.post(f"/api/attempts/{a['id']}/pause", headers=hdr(), json={}).status_code == 409
    clock.advance(2)
    duplicate = client.post(f"/api/attempts/{a['id']}/start", headers=hdr(), json={"media_ready": True}).json()
    assert duplicate["timing"]["deadline_at_ms"] == deadline
    assert duplicate["timing"]["remaining_ms"] == 118000 and duplicate["audio_elapsed_ms"] == 2000
    assert answer(client, a, "t01-q001", "A").status_code == 200
    clock.advance(118)
    expired = client.get(f"/api/attempts/{a['id']}").json()
    assert expired["status"] == "expired"
    assert answer(client, a, "t01-q001", "B", revision=1).status_code == 410
    report = client.get(f"/api/attempts/{a['id']}/report").json()
    assert report["summary"]["total"] == 1 and report["summary"]["correct"] == 1
    assert report["attempt"]["timer_config"]["duration_seconds"] == 120


def test_cross_exam_exact_listening_queue_and_question_mapping(custom_exam_client, clock):
    client = custom_exam_client
    response = custom_exam(client, ["t02-p3-q032", "t01-p1-q3", "t01-p1-q1", "t01-p1-q3"],
                           exam_ids=["test-01", "test-02"])
    assert response.status_code == 200, response.text
    a = start(client, response.json())
    assert a["timing"]["phase"] == "listening" and a["question_count"] == 5
    assert len(a["audio_queue"]) == 3
    assert sum(item["end_seconds"] - item["start_seconds"] for item in a["audio_queue"]) == 11
    assert set(a["timing"]["phase_question_ids"]) == {q["id"] for q in a["questions"]}
    assert {qid for item in a["audio_queue"] for qid in item["question_ids"]} == {q["id"] for q in a["questions"]}
    clock.advance(4)
    state = client.get(f"/api/attempts/{a['id']}/clock").json()
    assert state["audio_elapsed_ms"] == 4000 and state["timing"]["remaining_ms"] == 116000


@pytest.mark.parametrize("poll_at", [5, 7, 121])
def test_mixed_custom_exam_shares_one_budget_with_reading(custom_exam_client, clock, poll_at):
    client = custom_exam_client
    response = custom_exam(client, ["t01-p3-q032", "t02-p7-g147"], exam_ids=["test-01", "test-02"])
    assert response.status_code == 200, response.text
    a = start(client, response.json())
    assert a["timing"]["phase"] == "practice" and a["timing"]["remaining_ms"] == 120000
    assert set(a["timing"]["phase_question_ids"]) == {q["id"] for q in a["questions"]}
    assert answer(client, a, "t02-q147", "A").status_code == 200
    assert answer(client, a, "t01-q032", "A").status_code == 200
    start_wall = a["timing"]["server_time_ms"]
    clock.advance(poll_at)
    state = client.get(f"/api/attempts/{a['id']}").json()
    assert state["timer_config"] == {"kind": "countdown", "duration_seconds": 120}
    if poll_at >= 120:
        assert state["status"] == "expired"
        assert client.get(f"/api/attempts/{a['id']}/report").json()["summary"]["total"] == 6
        return
    assert state["timing"]["phase"] == "practice" and state["status"] == "running"
    assert set(state["timing"]["phase_question_ids"]) == {q["id"] for q in a["questions"]}
    assert state["timing"]["remaining_ms"] == (120 - poll_at) * 1000
    assert state["timing"]["deadline_at_ms"] == start_wall + 120000
    assert state["timing"]["elapsed_ms"] == state["audio_elapsed_ms"] == poll_at * 1000
    assert client.get(f"/api/attempts/{a['id']}/clock").json()["audio_elapsed_ms"] == poll_at * 1000
    assert answer(client, a, "t01-q032", "B", revision=1).status_code == 200
    assert answer(client, a, "t02-q147", "A", revision=1).status_code == 200
    # Media telemetry cannot reset the sole total countdown.
    media = client.put(f"/api/attempts/{a['id']}/media-state", headers=hdr(),
        json={"queue_index": 0, "position_seconds": 0, "playback_rate": 1}).json()
    assert media["timing"]["deadline_at_ms"] == start_wall + 120000
    clock.advance(120 - poll_at)
    assert client.get(f"/api/attempts/{a['id']}/clock").json()["status"] == "expired"


@pytest.mark.parametrize("kind", ["countdown", "countup", "none"])
def test_reading_only_custom_keeps_personal_timer(custom_exam_client, clock, kind):
    client = custom_exam_client
    result = custom_exam(client, ["t01-p7-g147"], kind=kind)
    assert result.status_code == 200, result.text
    a = start(client, result.json())
    assert a["timing"]["phase"] == "reading" and a["timing"]["kind"] == kind
    assert a["timing"]["phase_question_ids"] == ["t01-q147", "t01-q148", "t01-q149"]
    assert a["audio_queue"] == [] and not a["timing"]["can_pause"]
    assert answer(client, a, "t01-q147", "A").status_code == 200
    clock.advance(120)
    assert client.get(f"/api/attempts/{a['id']}").json()["status"] == ("expired" if kind == "countdown" else "running")


@pytest.mark.parametrize("seconds", [0, -1, None])
def test_listening_custom_exam_requires_positive_deadline(custom_exam_client, seconds):
    response = custom_exam(custom_exam_client, ["t01-p1-q1"], seconds=seconds)
    assert response.status_code == 400 and response.json()["code"] == "duration_required"


@pytest.mark.parametrize("kind", ["countdown", "countup", "none"])
@pytest.mark.parametrize("mixed", [False, True])
def test_listening_custom_keeps_personal_timer_and_strict_audio(custom_exam_client, clock, kind, mixed):
    client = custom_exam_client
    groups = ["t01-p1-q1"] + (["t01-p7-g147"] if mixed else [])
    response = custom_exam(client, groups, kind=kind, seconds=120 if kind == "countdown" else None)
    assert response.status_code == 200, response.text
    a = start(client, response.json())
    phase = "practice" if mixed else "listening"
    assert a["timing"]["phase"] == phase and a["timing"]["kind"] == kind
    assert set(a["timing"]["phase_question_ids"]) == {q["id"] for q in a["questions"]}
    assert a["audio_queue"] and not a["timing"]["can_pause"]
    assert client.post(f"/api/attempts/{a['id']}/pause", headers=hdr(), json={}).status_code == 409
    assert answer(client, a, "t01-q001", "A").status_code == 200
    if mixed:
        assert answer(client, a, "t01-q147", "A").status_code == 200
    clock.advance(4)
    for endpoint in (f"/api/attempts/{a['id']}", f"/api/attempts/{a['id']}/clock"):
        state = client.get(endpoint).json()
        assert state["audio_elapsed_ms"] == state["timing"]["elapsed_ms"] == 4000
        assert state["timing"]["remaining_ms"] == (116000 if kind == "countdown" else None)
        assert (state["timing"]["deadline_at_ms"] is None) == (kind != "countdown")
    clock.advance(117)
    state = client.get(f"/api/attempts/{a['id']}").json()
    assert state["status"] == ("expired" if kind == "countdown" else "running")
    if kind != "countdown":
        assert state["audio_elapsed_ms"] == 121000
        assert answer(client, a, "t01-q001", "B", revision=1).status_code == 200


@pytest.mark.parametrize("seconds", [4, 5])
def test_mixed_custom_keeps_short_shared_budget_and_all_questions_editable(custom_exam_client, clock, seconds):
    client = custom_exam_client
    response = custom_exam(client, ["t01-p3-q032", "t01-p7-g147"], seconds=seconds)
    assert response.status_code == 200, response.text
    a = start(client, response.json())
    assert a["timing"]["phase"] == "practice" and a["timing"]["remaining_ms"] == seconds * 1000
    assert answer(client, a, "t01-q032", "A").status_code == 200
    assert answer(client, a, "t01-q147", "A").status_code == 200
    clock.advance(seconds)
    assert client.get(f"/api/attempts/{a['id']}/clock").json()["status"] == "expired"


@pytest.mark.parametrize("kind", ["countdown", "countup", "none"])
def test_mixed_part_exam_uses_shared_phase_and_audio_clock(custom_exam_client, clock, kind):
    client = custom_exam_client
    a = start(client, create(client, parts=[1, 5], mode="exam",
        timer={"kind": kind, "duration_seconds": 120}))
    assert a["timing"]["phase"] == "practice" and a["audio_queue"]
    assert set(a["timing"]["phase_question_ids"]) == {q["id"] for q in a["questions"]}
    assert not a["timing"]["can_pause"]
    assert answer(client, a, "t01-q001", "A").status_code == 200
    assert answer(client, a, "t01-q101", "A").status_code == 200
    assert client.post(f"/api/attempts/{a['id']}/pause", headers=hdr(), json={}).status_code == 409
    clock.advance(4)
    dto = client.get(f"/api/attempts/{a['id']}").json()
    state = client.get(f"/api/attempts/{a['id']}/clock").json()
    assert dto["audio_elapsed_ms"] == state["audio_elapsed_ms"] == state["timing"]["elapsed_ms"] == 4000
    assert state["timing"]["remaining_ms"] == (116000 if kind == "countdown" else None)
    clock.advance(116)
    state = client.get(f"/api/attempts/{a['id']}/clock").json()
    assert state["status"] == ("expired" if kind == "countdown" else "running")


def test_custom_exam_never_falls_back_to_unselected_part_audio(custom_exam_client, library_root):
    path = library_root / "audio-cues.json"
    cues = json.loads(path.read_text())
    cues["exams"]["test-01"]["groups"] = []
    path.write_text(json.dumps(cues), encoding="utf-8")
    custom_exam_client.app.state.services.library.load()
    response = custom_exam(custom_exam_client, ["t01-p1-q1"])
    assert response.status_code == 409 and response.json()["code"] == "cues_not_ready"
