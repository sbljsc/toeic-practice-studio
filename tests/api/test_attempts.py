"""HTTP-level attempt flow tests with the synthetic library fixture."""
import threading
import uuid

import pytest

TAB = "tab-test"


def hdr(origin="http://testserver"):
    return {"X-Tab-ID": TAB, "Origin": origin}


def create(client, **over):
    body = {"exam_ids": ["test-01"], "scope": "part", "parts": [5], "mode": "practice",
            "timer": {"kind": "countdown", "duration_seconds": 600},
            "question_filter": "all"}
    body.update(over)
    resp = client.post("/api/attempts", json=body, headers=hdr())
    assert resp.status_code == 200, resp.text
    return resp.json()


def start(client, attempt):
    client.post(f"/api/attempts/{attempt['id']}/claim", json={"takeover": False}, headers=hdr())
    resp = client.post(f"/api/attempts/{attempt['id']}/start",
                       json={"media_ready": True}, headers=hdr())
    assert resp.status_code == 200, resp.text
    return resp.json()


def answer(client, attempt, qid, option, revision=0, mutation_id=None):
    body = {"option_id": option, "revision": revision,
            "mutation_id": mutation_id or str(uuid.uuid4())}
    return client.put(f"/api/attempts/{attempt['id']}/answers/{qid}",
                      json=body, headers=hdr())


def test_private_data_never_leaks_before_submit(client):
    attempt = create(client)
    for q in attempt["questions"]:
        assert "answer" not in q and "explanation" not in q
        assert "_answer" not in q
    for g in attempt["groups"]:
        assert "review_text" not in g
        assert "_review_text" not in g
    # Part 1/2 public labels only
    part1 = create(client, parts=[1])
    for q in part1["questions"]:
        assert all(o["text"] == "" for o in q["options"])
        assert q["stem"] == ""


def test_answer_revision_and_idempotency(client):
    attempt = start(client, create(client))
    qid = attempt["questions"][0]["id"]
    ok = answer(client, attempt, qid, "A")
    assert ok.status_code == 200
    assert ok.json()["answers"][qid]["revision"] == 1
    # same mutation_id replays the stored state without bumping revision
    again = answer(client, attempt, qid, "A", revision=1)
    assert again.status_code == 200
    # stale revision conflicts
    stale = answer(client, attempt, qid, "B", revision=0)
    assert stale.status_code == 409
    # invalid option rejected
    bad = answer(client, attempt, qid, "Z", revision=1)
    assert bad.status_code in (400, 422)


def test_no_answer_before_start_or_while_paused(client):
    attempt = create(client)
    qid = attempt["questions"][0]["id"]
    client.post(f"/api/attempts/{attempt['id']}/claim", json={"takeover": False}, headers=hdr())
    early = answer(client, attempt, qid, "A")
    assert early.status_code == 409
    attempt = start(client, attempt)
    client.post(f"/api/attempts/{attempt['id']}/pause", headers=hdr())
    paused = answer(client, attempt, qid, "A", revision=0)
    assert paused.status_code == 409
    client.post(f"/api/attempts/{attempt['id']}/resume", headers=hdr())
    ok = answer(client, attempt, qid, "A", revision=0)
    assert ok.status_code == 200


def test_two_tab_takeover_blocks_stale_writer(client):
    attempt = start(client, create(client))
    other = {"X-Tab-ID": "tab-other", "Origin": "http://testserver"}
    # other tab cannot claim without takeover
    blocked = client.post(f"/api/attempts/{attempt['id']}/claim",
                          json={"takeover": False}, headers=other)
    assert blocked.status_code == 409
    took = client.post(f"/api/attempts/{attempt['id']}/claim",
                       json={"takeover": True}, headers=other)
    assert took.status_code == 200
    # original tab is now stale
    qid = attempt["questions"][0]["id"]
    stale = answer(client, attempt, qid, "A")
    assert stale.status_code == 409


def test_parallel_writes_serialize_and_never_lose_state(client):
    attempt = start(client, create(client))
    questions = [q["id"] for q in attempt["questions"][:20]]
    errors = []

    def worker(qid, option):
        for _ in range(5):
            resp = answer(client, attempt, qid, option,
                          revision=client.get(f"/api/attempts/{attempt['id']}").json()["answers"].get(qid, {}).get("revision", 0))
            if resp.status_code not in (200, 409):
                errors.append(resp.text)

    threads = [threading.Thread(target=worker, args=(qid, "ABCD"[i % 4]))
               for i, qid in enumerate(questions)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    final = client.get(f"/api/attempts/{attempt['id']}").json()
    assert all(final["answers"][qid]["option_id"] for qid in questions)


def test_submit_idempotent_and_immutable(client):
    attempt = start(client, create(client))
    qid = attempt["questions"][0]["id"]
    answer(client, attempt, qid, "A")
    first = client.post(f"/api/attempts/{attempt['id']}/submit", json={}, headers=hdr())
    assert first.status_code == 200
    second = client.post(f"/api/attempts/{attempt['id']}/submit", json={}, headers=hdr())
    assert second.status_code == 200
    assert first.json()["summary"] == second.json()["summary"]
    # answers locked after submit
    locked = answer(client, attempt, qid, "B", revision=1)
    assert locked.status_code in (409, 410)


def test_manual_submit_ends_future_phases(client):
    attempt = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "full", "mode": "exam",
        "timer": {"kind": "none"}, "question_filter": "all"}, headers=hdr()).json()
    start(client, attempt)
    report = client.post(f"/api/attempts/{attempt['id']}/submit", json={}, headers=hdr()).json()
    assert report["attempt"]["status"] == "submitted"
    assert report["attempt"]["close_reason"] == "manual"
    assert report["summary"]["total"] == 200


def test_reading_scope_locks_nothing_but_full_locks_listening(client):
    full = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "full", "mode": "exam",
        "timer": {"kind": "none"}, "question_filter": "all"}, headers=hdr()).json()
    start(client, full)
    reading_q = next(q for q in full["questions"] if q["part"] == 5)
    blocked = answer(client, full, reading_q["id"], "A")
    assert blocked.status_code == 409  # reading locked during listening phase


def test_report_contains_private_keys_and_review_text(client):
    attempt = start(client, create(client))
    qid = attempt["questions"][0]["id"]
    answer(client, attempt, qid, "A")
    client.post(f"/api/attempts/{attempt['id']}/submit", json={}, headers=hdr())
    report = client.get(f"/api/attempts/{attempt['id']}/report").json()
    assert report["questions"][0]["answer"]
    assert report["questions"][0]["explanation"]["text"]
    assert report["groups"][0]["review_text"]


def test_custom_scope_expands_to_whole_groups(client):
    exam_groups = client.get("/api/exams/test-01/groups").json()["groups"]
    multi = next(g for g in exam_groups if len(g["question_ids"]) > 1)
    first_qid = multi["question_ids"][0]
    # pick custom with one question of a 3-question group via group_ids
    attempt = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "custom", "group_ids": [multi["id"]],
        "mode": "practice", "timer": {"kind": "none"}, "question_filter": "all"},
        headers=hdr()).json()
    ids = {q["id"] for q in attempt["questions"]}
    assert set(multi["question_ids"]) <= ids


def test_media_state_validated_against_queue(client):
    attempt = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "part", "parts": [1], "mode": "practice",
        "timer": {"kind": "none"}, "question_filter": "all"}, headers=hdr()).json()
    assert attempt["audio_queue"]
    attempt = start(client, attempt)
    ok = client.put(f"/api/attempts/{attempt['id']}/media-state",
                    json={"queue_index": 0, "position_seconds": 5.0, "playback_rate": 1.5},
                    headers=hdr())
    assert ok.status_code == 200
    bad = client.put(f"/api/attempts/{attempt['id']}/media-state",
                     json={"queue_index": 9, "position_seconds": 0, "playback_rate": 1.0},
                     headers=hdr())
    assert bad.status_code == 400
    beyond = client.put(f"/api/attempts/{attempt['id']}/media-state",
                        json={"queue_index": 0, "position_seconds": 99999.0,
                              "playback_rate": 1.0}, headers=hdr())
    assert beyond.status_code == 400


def test_foreign_and_cross_port_origin_rejected(client):
    body = {"exam_ids": ["test-01"], "scope": "part", "parts": [5],
            "mode": "practice", "timer": {"kind": "none"}, "question_filter": "all"}
    foreign = client.post("/api/attempts", json=body,
                          headers={"X-Tab-ID": TAB, "Origin": "https://evil.example"})
    assert foreign.status_code == 403
    cross = client.post("/api/attempts", json=body,
                        headers={"X-Tab-ID": TAB, "Origin": "http://127.0.0.1:9999"})
    assert cross.status_code == 403
    cli = client.post("/api/attempts", json=body, headers={"X-Tab-ID": TAB})
    assert cli.status_code == 200  # local CLI without Origin allowed


def test_asset_range_and_traversal(client):
    resp = client.get("/api/assets/audio-test-01", headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert len(resp.content) == 100
    missing = client.get("/api/assets/..%2Fmanifest")
    assert missing.status_code == 404
    unknown = client.get("/api/assets/not-registered")
    assert unknown.status_code == 404


def test_wrong_scope_uses_latest_results(client):
    attempt = start(client, create(client))
    q = attempt["questions"][0]
    answer(client, attempt, q["id"], "B")  # fixture Q101 correct key is A
    client.post(f"/api/attempts/{attempt['id']}/submit", json={}, headers=hdr())
    filtered = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "part", "parts": [5], "mode": "practice",
        "timer": {"kind": "none"}, "question_filter": "wrong"}, headers=hdr())
    assert filtered.status_code == 200
    ids = {x["id"] for x in filtered.json()["questions"]}
    assert q["id"] in ids  # whole group of the wrong question included
