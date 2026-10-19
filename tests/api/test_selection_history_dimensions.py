"""Historical selection tracks actual answers separately from bookmarks."""
import json
import uuid

import pytest

from test_attempts import hdr


def closed_round(client, answers=(), *, part=5, interrupted=False, late=False):
    response = client.post("/api/attempts", headers=hdr(), json={"exam_ids": ["test-01"],
        "scope": "part", "parts": [part], "mode": "practice", "timer": {"kind": "none"}})
    assert response.status_code == 200, response.text
    a = response.json()
    assert client.post(f"/api/attempts/{a['id']}/start", headers=hdr(), json={"media_ready": True}).status_code == 200
    for number, option, flagged in answers:
        saved = client.put(f"/api/attempts/{a['id']}/answers/t01-q{number:03d}", headers=hdr(),
            json={"option_id": option, "flagged": flagged, "revision": 0, "mutation_id": str(uuid.uuid4())})
        assert saved.status_code == 200, saved.text
    if interrupted and not late:
        assert client.post(f"/api/attempts/{a['id']}/interrupt", headers=hdr(),
                           json={"reason": "media_failure"}).status_code == 200
    assert client.post(f"/api/attempts/{a['id']}/submit", headers=hdr(), json={}).status_code == 200
    if interrupted and late:
        assert client.post(f"/api/attempts/{a['id']}/interrupt", headers=hdr(),
            json={"reason": "queued_media_failure", "event_id": str(uuid.uuid4())}).status_code == 200
    return a


def filtered_ids(client, question_filter, *, part=5):
    response = client.post("/api/attempts", headers=hdr(), json={"exam_ids": ["test-01"],
        "scope": "part", "parts": [part], "mode": "practice", "timer": {"kind": "none"},
        "question_filter": question_filter})
    if response.status_code == 409:
        assert response.json()["code"] == "empty_scope", response.text
        return set()
    assert response.status_code == 200, response.text
    result = response.json()
    ids = [q["id"] for q in result["questions"]]
    assert len(ids) == len(set(ids)) == result["question_count"]
    return set(ids)


def test_three_wrong_questions_survive_later_partial_round(client):
    closed_round(client, [(101, "D", True), (102, "D", False), (103, "D", False)])
    closed_round(client, [(102, "D", False)])  # q101/q103 omitted, matching the real UI case
    assert filtered_ids(client, "wrong") == {"t01-q101", "t01-q102", "t01-q103"}
    assert filtered_ids(client, "bookmarked") == {"t01-q101"}
    assert filtered_ids(client, "unanswered") == {f"t01-q{n:03d}" for n in range(104, 131)}


@pytest.mark.parametrize("explicit_empty", [False, True])
def test_wrong_then_unanswered_keeps_wrong_and_is_not_never_answered(client, explicit_empty):
    closed_round(client, [(101, "B", False)])
    closed_round(client, [(101, None, False)] if explicit_empty else [])
    assert filtered_ids(client, "wrong") == {"t01-q101"}
    assert "t01-q101" not in filtered_ids(client, "unanswered")


def test_wrong_then_correct_then_unanswered_never_revives_wrong(client):
    closed_round(client, [(101, "B", False)])
    closed_round(client, [(101, "A", False)])
    closed_round(client, [(101, None, False)])
    assert filtered_ids(client, "wrong") == set()
    assert "t01-q101" not in filtered_ids(client, "unanswered")


def test_wrong_and_bookmarked_are_independent_filters(client):
    closed_round(client, [(101, "B", True)])
    assert filtered_ids(client, "wrong") == filtered_ids(client, "bookmarked") == {"t01-q101"}
    assert "t01-q101" not in filtered_ids(client, "unanswered")
    closed_round(client, [(101, None, False)])  # explicit unmark is not a new graded answer
    assert filtered_ids(client, "wrong") == {"t01-q101"}
    assert filtered_ids(client, "bookmarked") == set()
    closed_round(client, [(101, "A", True)])
    assert filtered_ids(client, "wrong") == set() and filtered_ids(client, "bookmarked") == {"t01-q101"}


def test_bookmarked_without_any_answer_is_still_unanswered(client):
    closed_round(client, [(101, None, True)])
    closed_round(client)  # an untouched round does not unmark the question
    assert filtered_ids(client, "wrong") == set()
    assert filtered_ids(client, "bookmarked") == {"t01-q101"}
    assert "t01-q101" in filtered_ids(client, "unanswered")


@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize("valid_option,invalid_option,valid_flag,invalid_flag", [
    ("B", "A", False, True), ("A", "B", True, False)])
def test_interrupted_answers_and_marks_do_not_pollute_valid_history(client, late, valid_option, invalid_option, valid_flag, invalid_flag):
    closed_round(client, [(101, valid_option, valid_flag)])
    closed_round(client, [(101, invalid_option, invalid_flag)], interrupted=True, late=late)
    closed_round(client)  # later blank snapshot must change neither dimension
    assert filtered_ids(client, "wrong") == ({"t01-q101"} if valid_option == "B" else set())
    assert filtered_ids(client, "bookmarked") == ({"t01-q101"} if valid_flag else set())
    assert "t01-q101" not in filtered_ids(client, "unanswered")


def test_repeated_versions_keep_actual_answer_history_and_corrected_keys_are_excluded(client, library_root):
    closed_round(client, [(101, "B", True), (102, "D", False)])
    manifest_path = library_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()); manifest["version"] = "v2-label-only"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    client.app.state.services.library.load()
    closed_round(client)  # new whole-library version, unchanged keys
    assert filtered_ids(client, "wrong") == {"t01-q101", "t01-q102"}
    closed_round(client, [(101, "A", True)])
    manifest["version"] = "v3-label-only"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    client.app.state.services.library.load()
    closed_round(client)
    assert filtered_ids(client, "wrong") == {"t01-q102"}
    assert filtered_ids(client, "bookmarked") == {"t01-q101"}
    # A genuine key correction invalidates only that canonical question's old facts.
    exam_path = library_root / "exams/test-01.json"
    exam = json.loads(exam_path.read_text()); exam["questions"][101]["answer"] = "D"
    exam_path.write_text(json.dumps(exam), encoding="utf-8")
    client.app.state.services.library.load()
    assert filtered_ids(client, "wrong") == set()
    assert filtered_ids(client, "bookmarked") == {"t01-q101"}
    assert "t01-q102" in filtered_ids(client, "unanswered")


def test_filters_still_expand_touched_material_to_whole_group(client):
    closed_round(client, [(131, "B", True)], part=6)
    closed_round(client, part=6)
    expected = {"t01-q131", "t01-q132", "t01-q133"}
    assert filtered_ids(client, "wrong", part=6) == expected
    assert filtered_ids(client, "bookmarked", part=6) == expected
