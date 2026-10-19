"""Remaining senior findings: wall jumps, private candidates, late evidence."""
import json

import pytest

from test_review_repairs import HEADERS, TAB, answer, create, start


@pytest.mark.parametrize("wall_jump", [-3600, 3600])
def test_exact_senior_part2_wall_only_jump_preserves_fifty_seconds(app_services, clock, wall_jump):
    svc = app_services
    a = create(svc, scope="part", parts=[2], mode="exam", seconds=60)
    start(svc, a)
    clock.advance(10)
    before = svc.attempts.get(a["id"])
    before_timer = json.loads(svc.store.query_one("SELECT timer FROM attempts WHERE id=?", (a["id"],))["timer"])
    monotonic_before, identity_before = clock.monotonic(), clock.identity
    clock.wall_now += wall_jump  # exactly the senior probe: no monotonic movement
    after = svc.attempts.get(a["id"])
    after_timer = json.loads(svc.store.query_one("SELECT timer FROM attempts WHERE id=?", (a["id"],))["timer"])
    assert clock.monotonic() == monotonic_before and clock.identity == identity_before
    assert before["timing"]["remaining_ms"] == after["timing"]["remaining_ms"] == 50000
    assert before["timing"]["elapsed_ms"] == after["timing"]["elapsed_ms"] == 10000
    assert after["status"] == "running" and after["integrity"] == "interrupted"
    assert after["interruptions"][-1]["reason"] == "clock_discontinuity"
    assert before_timer["current_phase_started_monotonic"] == after_timer["current_phase_started_monotonic"]
    assert svc.store.query_one("SELECT report FROM attempts WHERE id=?", (a["id"],))["report"] is None


@pytest.mark.parametrize("scope,elapsed", [("reading", 10), ("listening", 10), ("full", 10), ("full", 125)])
@pytest.mark.parametrize("wall_jump", [-7200, 7200])
def test_same_process_wall_jump_never_changes_monotonic_budget(app_services, clock, scope, elapsed, wall_jump):
    svc = app_services
    a = create(svc, scope=scope, mode="exam"); start(svc, a)
    clock.advance(elapsed)
    before = svc.attempts.get(a["id"])
    anchor = json.loads(svc.store.query_one("SELECT timer FROM attempts WHERE id=?", (a["id"],))["timer"])["current_phase_started_monotonic"]
    clock.wall_now += wall_jump
    clock.advance(3)
    after = svc.attempts.get(a["id"])
    assert after["status"] == "running"
    assert after["timing"]["phase"] == before["timing"]["phase"]
    assert after["timing"]["elapsed_ms"] == before["timing"]["elapsed_ms"] + 3000
    assert after["timing"]["remaining_ms"] == before["timing"]["remaining_ms"] - 3000
    assert after["timing"]["deadline_at_ms"] - after["timing"]["server_time_ms"] == after["timing"]["remaining_ms"]
    saved = json.loads(svc.store.query_one("SELECT timer FROM attempts WHERE id=?", (a["id"],))["timer"])
    assert saved["current_phase_started_monotonic"] == anchor
    assert after["integrity"] == "interrupted"
    again = svc.attempts.get(a["id"])
    assert again["interruptions"] == after["interruptions"]


@pytest.mark.parametrize("part", [1, 2])
@pytest.mark.parametrize("status", ["ready", "running", "paused"])
def test_private_candidates_unavailable_until_closed(client, part, status):
    svc = client.app.state.services
    a = create(svc, parts=[part])
    if status != "ready":
        start(svc, a)
    if status == "paused":
        svc.attempts.pause(a["id"], TAB)
    url = f"/api/attempts/{a['id']}/candidates/{a['questions'][0]['id']}"
    blocked = client.get(url)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "attempt_open"
    assert "keywordalpha" not in blocked.text and "wordbeta" not in blocked.text
    svc.attempts.submit(a["id"], TAB)
    allowed = client.get(url)
    assert allowed.status_code == 200 and allowed.json()["candidates"]


def test_private_candidates_can_authoritatively_close_expired_attempt(client, clock):
    svc = client.app.state.services
    a = create(svc, parts=[1], seconds=1); start(svc, a)
    clock.advance(1)
    response = client.get(f"/api/attempts/{a['id']}/candidates/{a['questions'][0]['id']}")
    assert response.status_code == 200 and response.json()["candidates"]
    persisted = svc.store.query_one("SELECT status,report FROM attempts WHERE id=?", (a["id"],))
    assert persisted["status"] == "expired" and persisted["report"]


def test_late_interrupt_excludes_existing_vocab_only_from_current_thresholds(client):
    svc = client.app.state.services
    a = create(svc); start(svc, a)
    for q in a["questions"][:3]:
        answer(svc, a, q=q, option="D")  # fixture first three keys A/B/C
    svc.attempts.submit(a["id"], TAB)
    for q in a["questions"][:3]:
        svc.attempts.put_review(a["id"], q["id"], {"causes": ["meaning"],
            "words": [{"term": "reliabilityword", "causal": True}]})
    before = client.get("/api/vocabulary").json()["entries"][0]
    assert before["status"] == "must_learn" and before["question_count"] == 3
    evidence = [dict(r) for r in svc.store.query("SELECT * FROM vocab_evidence")]
    grades = svc.store.query_one("SELECT report FROM attempts WHERE id=?", (a["id"],))["report"]
    response = client.post(f"/api/attempts/{a['id']}/interrupt", headers=HEADERS,
        json={"reason": "offline_media_stall", "event_id": "queued-event", "occurred_at_ms": 123})
    assert response.status_code == 200 and response.json()["integrity"] == "interrupted"
    after = client.get("/api/vocabulary").json()["entries"][0]
    assert after["question_count"] == after["material_count"] == 0
    assert after["status"] == "candidate" and after["evidence"] == []
    assert after["lifetime_question_count"] == 3
    assert [dict(r) for r in svc.store.query("SELECT * FROM vocab_evidence")] == evidence
    assert svc.store.query_one("SELECT report FROM attempts WHERE id=?", (a["id"],))["report"] == grades
    patched = client.patch("/api/vocabulary/reliabilityword%7C%7Cmeaning", headers=HEADERS,
                           json={"mastered": False})
    assert patched.status_code == 200 and patched.json()["entries"][0]["question_count"] == 0
    # Unrelated valid evidence remains eligible and does not revive old rows.
    b = create(svc); start(svc, b); answer(svc, b, option="D"); svc.attempts.submit(b["id"], TAB)
    svc.attempts.put_review(b["id"], b["questions"][0]["id"], {"causes": ["meaning"],
        "words": [{"term": "reliabilityword", "causal": True}]})
    current = client.get("/api/vocabulary").json()["entries"][0]
    assert current["question_count"] == 1 and current["lifetime_question_count"] == 3
    assert current["evidence"][0]["attempt_id"] == b["id"]
