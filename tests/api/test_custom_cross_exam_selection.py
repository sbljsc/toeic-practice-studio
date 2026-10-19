"""Custom groups are validated across selected exams, then selected per source."""
import json
import uuid

import pytest

from conftest import build_exam
from test_attempts import hdr, start


@pytest.fixture
def multi_exam_client(client, library_root):
    manifest_path = library_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    cues_path = library_root / "audio-cues.json"
    cues = json.loads(cues_path.read_text())
    for index in (1, 2, 3):
        exam_id, prefix = f"test-{index:02d}", f"t{index:02d}"
        raw = build_exam(prefix, f"TEST {index:02d}")
        # Match the browser's reported Part 3 group IDs exactly.
        group = next(g for g in raw["groups"] if g["id"] == f"{prefix}-p3-g32")
        group["id"] = f"{prefix}-p3-q032"
        for q in raw["questions"]:
            if q["id"] in group["question_ids"]:
                q["group_id"] = group["id"]
        raw["audio"].update(asset_id=f"audio-{exam_id}", path=f"media/{exam_id}.mp3")
        (library_root / f"exams/{exam_id}.json").write_text(json.dumps(raw), encoding="utf-8")
        if index != 1:
            manifest["exams"].append({"id": exam_id, "title": f"TEST {index:02d}",
                "version": "test-lib-v1", "path": f"exams/{exam_id}.json",
                "question_count": 200, "validated": True})
            manifest["assets"].append({"id": f"audio-{exam_id}", "path": f"media/{exam_id}.mp3",
                                       "media_type": "audio/mpeg"})
            (library_root / f"media/{exam_id}.mp3").write_bytes(b"\xff\xfb" + b"\0" * 4096)
        cues["exams"][exam_id] = {**cues["exams"]["test-01"], "groups": [
            {"part": 3, "first_question": 32, "last_question": 34,
             "start_seconds": 60, "end_seconds": 65, "verified": True}]}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    cues_path.write_text(json.dumps(cues), encoding="utf-8")
    client.app.state.services.library.load()
    return client


def custom(client, group_ids, exam_ids=None):
    return client.post("/api/attempts", headers=hdr(), json={
        "exam_ids": exam_ids or ["test-01", "test-02"], "scope": "custom",
        "group_ids": group_ids, "mode": "practice", "question_filter": "all",
        "timer": {"kind": "countdown", "duration_seconds": 120}})


@pytest.mark.parametrize("duplicate_requests", [False, True])
def test_cross_exam_listening_groups_roundtrip(multi_exam_client, duplicate_requests):
    client = multi_exam_client
    groups = ["t01-p3-q032", "t02-p3-q032"]
    response = custom(client, groups * (2 if duplicate_requests else 1),
        ["test-01", "test-02", "test-01"] if duplicate_requests else None)
    assert response.status_code == 200, response.text
    a = response.json()
    assert a["exam_ids"] == ["test-01", "test-02"]
    assert a["question_count"] == 6 and len({q["id"] for q in a["questions"]}) == 6
    assert [g["id"] for g in a["groups"]] == groups
    assert a["parts"] == [3] and len(a["timing"]["phase_question_ids"]) == 6
    assert len(a["audio_queue"]) == 2
    assert {item["asset_id"] for item in a["audio_queue"]} == {"audio-test-01", "audio-test-02"}
    queue_ids = [qid for item in a["audio_queue"] for qid in item["question_ids"]]
    assert len(queue_ids) == len(set(queue_ids)) == 6
    assert set(queue_ids) == {q["id"] for q in a["questions"]}
    for item in a["audio_queue"]:
        assert (item["start_seconds"], item["end_seconds"]) == (60, 65)
    started = start(client, a)
    assert started["status"] == "running" and started["timing"]["remaining_ms"] == 120000
    for q in a["questions"]:
        saved = client.put(f"/api/attempts/{a['id']}/answers/{q['id']}", headers=hdr(),
            json={"option_id": "A", "revision": 0, "mutation_id": str(uuid.uuid4())})
        assert saved.status_code == 200, saved.text
    reloaded = client.get(f"/api/attempts/{a['id']}").json()
    assert len(reloaded["answers"]) == 6 and reloaded["audio_queue"] == a["audio_queue"]
    closed = client.post(f"/api/attempts/{a['id']}/submit", headers=hdr(), json={}).json()
    assert closed["summary"]["total"] == 6 and len(closed["groups"]) == 2


@pytest.mark.parametrize("groups,parts", [
    (["t01-p7-g147", "t02-p7-g147"], [7]),
    (["t01-p6-g131", "t02-p7-g147"], [6, 7])])
def test_cross_exam_reading_groups(multi_exam_client, groups, parts):
    client = multi_exam_client
    response = custom(client, list(reversed(groups)) + groups)
    assert response.status_code == 200, response.text
    a = response.json()
    assert a["question_count"] == 6 and len({q["id"] for q in a["questions"]}) == 6
    assert [g["id"] for g in a["groups"]] == groups and a["parts"] == parts
    assert a["audio_queue"] == []
    assert start(client, a)["timing"]["remaining_ms"] == 120000


def test_selected_exam_can_have_no_matching_custom_group(multi_exam_client):
    response = custom(multi_exam_client, ["t02-p3-q032"])
    assert response.status_code == 200, response.text
    a = response.json()
    assert a["question_count"] == 3 and len(a["groups"]) == len(a["audio_queue"]) == 1
    assert {q["exam_id"] for q in a["questions"]} == {"test-02"}
    assert a["audio_queue"][0]["asset_id"] == "audio-test-02"


@pytest.mark.parametrize("bad_group", ["unknown-group", "t03-p3-q032", "t03-p7-g147"])
def test_unknown_or_unselected_exam_group_rejected(multi_exam_client, bad_group):
    client = multi_exam_client
    response = custom(client, ["t01-p3-q032", bad_group])
    assert response.status_code == 404 and response.json()["code"] == "group_not_found"
    assert bad_group in response.json()["detail"]
    assert client.app.state.services.store.query_one("SELECT COUNT(*) AS n FROM attempts")["n"] == 0
