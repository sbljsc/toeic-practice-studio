"""Listening exams schedule every selected full track on one authority clock."""
import json

import pytest

from test_attempts import answer, hdr, start
from test_custom_cross_exam_selection import multi_exam_client


@pytest.fixture
def different_length_client(multi_exam_client, library_root):
    exam_path = library_root / "exams/test-02.json"
    exam = json.loads(exam_path.read_text())
    exam["audio"]["duration_seconds"] = 160
    exam_path.write_text(json.dumps(exam), encoding="utf-8")
    cue_path = library_root / "audio-cues.json"
    cues = json.loads(cue_path.read_text())
    cues["exams"]["test-02"].update(source_duration_seconds=160,
        full_start_seconds=10, full_end_seconds=160)
    cue_path.write_text(json.dumps(cues), encoding="utf-8")
    multi_exam_client.app.state.services.library.load()
    return multi_exam_client


def create_listening(client, exam_ids, scope="listening"):
    response = client.post("/api/attempts", headers=hdr(), json={
        "exam_ids": exam_ids, "scope": scope, "mode": "exam", "question_filter": "all",
        "timer": {"kind": "none", "duration_seconds": 999}})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("exam_ids", [["test-01", "test-02"], ["test-02", "test-01"]])
def test_all_selected_tracks_share_summed_deadline(different_length_client, clock, exam_ids):
    client = different_length_client
    a = create_listening(client, exam_ids)
    assert a["question_count"] == 200 and len(a["audio_queue"]) == 2
    assert a["exam_ids"] == [item["exam_id"] for item in a["audio_queue"]] == sorted(exam_ids)
    assert {item["asset_id"] for item in a["audio_queue"]} == {"audio-test-01", "audio-test-02"}
    question_ids = {q["id"] for q in a["questions"]}
    queued_ids = []
    for item in a["audio_queue"]:
        assert len(item["question_ids"]) == 100
        own_ids = {q["id"] for q in a["questions"] if q["exam_id"] == item["exam_id"]}
        assert set(item["question_ids"]) == own_ids
        queued_ids.extend(item["question_ids"])
    assert len(queued_ids) == len(set(queued_ids)) == 200 and set(queued_ids) == question_ids
    assert queued_ids == [q["id"] for q in a["questions"]]
    started = start(client, a)
    deadline = started["timing"]["deadline_at_ms"]
    assert deadline == started["timing"]["server_time_ms"] + 270000
    assert started["timing"]["kind"] == "countdown" and started["timing"]["remaining_ms"] == 270000
    assert set(started["timing"]["phase_question_ids"]) == question_ids
    assert answer(client, a, "t01-q001", "A").status_code == 200
    first = a["audio_queue"][0]
    first_duration = first["end_seconds"] - first["start_seconds"]
    clock.advance(first_duration)
    boundary = client.get(f"/api/attempts/{a['id']}/clock").json()
    assert boundary["status"] == "running" and boundary["timing"]["phase"] == "listening"
    assert boundary["audio_elapsed_ms"] == first_duration * 1000
    assert boundary["timing"]["remaining_ms"] == (270 - first_duration) * 1000
    repeated = client.post(f"/api/attempts/{a['id']}/start", headers=hdr(), json={"media_ready": True}).json()
    assert repeated["timing"]["deadline_at_ms"] == deadline
    assert client.post(f"/api/attempts/{a['id']}/pause", headers=hdr(), json={}).status_code == 409
    assert answer(client, a, "t02-q001", "A").status_code == 200
    clock.advance(270 - first_duration)
    ended = client.get(f"/api/attempts/{a['id']}/clock").json()
    assert ended["status"] == "expired" and ended["timing"]["elapsed_ms"] == 270000
    report = client.get(f"/api/attempts/{a['id']}/report").json()
    assert report["summary"]["total"] == 200 and report["summary"]["correct"] == 2
    assert answer(client, a, "t02-q001", "B", revision=1).status_code == 410


@pytest.mark.parametrize("scope,mode", [
    ("listening", "exam"), ("part", "exam"), ("custom", "exam"),
    ("part", "practice"), ("custom", "practice"), ("reading", "practice")])
@pytest.mark.parametrize("duplicate", [False, True])
def test_reverse_sources_keep_canonical_question_and_audio_order(multi_exam_client, clock, scope, mode, duplicate):
    client = multi_exam_client
    response = client.post("/api/attempts", headers=hdr(), json={
        "exam_ids": ["test-02", "test-01"] + (["test-02"] if duplicate else []),
        "scope": scope, "mode": mode, "parts": [1],
        "group_ids": ["t02-p3-q032", "t01-p3-q032"],
        "timer": {"kind": "countdown", "duration_seconds": 300}})
    assert response.status_code == 200, response.text
    a = response.json()
    assert a["exam_ids"] == ["test-01", "test-02"]
    assert a["title"].startswith("TEST 01、TEST 02 ")
    ordered = [q["id"] for q in a["questions"]]
    assert len(ordered) == len(set(ordered)) == a["question_count"]
    assert a["questions"] == sorted(a["questions"], key=lambda q: (q["exam_id"], q["number"]))
    assert len(a["groups"]) == len({g["id"] for g in a["groups"]})
    assert [g["exam_id"] for g in a["groups"]] == sorted(g["exam_id"] for g in a["groups"])
    if scope == "reading":
        assert not a["audio_queue"]
        return
    queue = a["audio_queue"]
    assert ordered == [qid for item in queue for qid in item["question_ids"]]
    assert a["questions"][0]["exam_id"] == queue[0]["exam_id"] == "test-01"
    first_count = sum(q["exam_id"] == "test-01" for q in a["questions"])
    last_first = next(item for item in reversed(queue) if item["exam_id"] == "test-01")
    first_second = next(item for item in queue if item["exam_id"] == "test-02")
    assert ordered[first_count - 1] == last_first["question_ids"][-1]
    assert ordered[first_count] == first_second["question_ids"][0]
    running = start(client, a)
    assert running["timing"]["phase_question_ids"] == ordered
    if mode == "exam":
        boundary_seconds = sum(item["end_seconds"] - item["start_seconds"]
                               for item in queue if item["exam_id"] == "test-01")
        clock.advance(boundary_seconds)
        state = client.get(f"/api/attempts/{a['id']}/clock").json()
        assert state["status"] == "running" and state["audio_elapsed_ms"] == boundary_seconds * 1000
        # Queue projection at this exact offset advances to the second source.
        assert first_second["question_ids"][0] == ordered[first_count]


def test_duplicate_selected_exam_does_not_repeat_questions_or_audio(different_length_client):
    a = create_listening(different_length_client, ["test-01", "test-02", "test-01"])
    assert a["exam_ids"] == ["test-01", "test-02"]
    assert a["question_count"] == 200 and len({q["id"] for q in a["questions"]}) == 200
    assert len(a["audio_queue"]) == 2
    assert start(different_length_client, a)["timing"]["remaining_ms"] == 270000


def test_start_revalidates_second_selected_track(different_length_client, library_root):
    client = different_length_client
    a = create_listening(client, ["test-01", "test-02"])
    (library_root / "media/test-02.mp3").unlink()
    blocked = client.post(f"/api/attempts/{a['id']}/start", headers=hdr(), json={"media_ready": True})
    assert blocked.status_code == 409 and blocked.json()["code"] == "content_not_ready"
    assert client.get(f"/api/attempts/{a['id']}").json()["status"] == "ready"


@pytest.mark.parametrize("exam_id,seconds", [("test-01", 120), ("test-02", 150)])
@pytest.mark.parametrize("scope", ["listening", "full"])
def test_single_source_schedule_is_unchanged(different_length_client, clock, exam_id, seconds, scope):
    client = different_length_client
    a = start(client, create_listening(client, [exam_id], scope=scope))
    assert len(a["audio_queue"]) == 1 and len(a["audio_queue"][0]["question_ids"]) == 100
    assert a["timing"]["remaining_ms"] == seconds * 1000
    clock.advance(seconds + 1)
    state = client.get(f"/api/attempts/{a['id']}/clock").json()
    if scope == "full":
        assert state["status"] == "running" and state["timing"]["phase"] == "reading"
        assert state["timing"]["remaining_ms"] == 4499000
    else:
        assert state["status"] == "expired"
