"""Verified former writers can replay reliability events, never active writes."""
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from toeic_practice.app import create_app
from toeic_practice.clock import ManualClock
from toeic_practice.library import Library
from toeic_practice.store import Store

A, B = "offline-listening-owner", "reading-owner"


def headers(tab):
    return {"Origin": "http://testserver", "X-Tab-ID": tab}


def prepare(client, clock, *, legacy=False):
    svc = client.app.state.services
    a = svc.attempts.create({"exam_ids": ["test-01"], "scope": "full", "mode": "exam",
        "timer": {"kind": "none"}, "question_filter": "all"})
    svc.attempts.start(a["id"], A, True)
    event = {"reason": "offline_listening_failure", "event_id": "queued-listening-event",
             "occurred_at_ms": round(clock.wall() * 1000)}
    if legacy:
        # A pre-registry database has only the current owner's persisted row.
        with svc.store.transaction() as conn:
            conn.execute("DELETE FROM meta WHERE key != 'schema_version'")
    clock.advance(121)
    assert svc.attempts.get(a["id"])["timing"]["phase"] == "reading"
    takeover = client.post(f"/api/attempts/{a['id']}/claim", headers=headers(B), json={"takeover": True})
    assert takeover.status_code == 200 and takeover.json()["owner_tab_id"] == B
    return a, event


def database_row(client, attempt_id):
    return dict(client.app.state.services.store.query_one("SELECT * FROM attempts WHERE id=?", (attempt_id,)))


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("restart", [False, True])
def test_former_owner_replays_listening_event_during_reading_or_after_submit(client, clock, closed, restart):
    a, event = prepare(client, clock, legacy=True)
    aid = a["id"]
    reading_q = next(q for q in a["questions"] if q["part"] == 5)
    saved = client.put(f"/api/attempts/{aid}/answers/{reading_q['id']}", headers=headers(B),
        json={"option_id": "A", "revision": 0, "mutation_id": str(uuid.uuid4())})
    assert saved.status_code == 200
    if closed:
        assert client.post(f"/api/attempts/{aid}/submit", headers=headers(B), json={}).status_code == 200
    if restart:
        previous = client.app.state.services
        path, root, backup_root = previous.store.path, previous.library.root, previous.backups.root
        previous.store.close()
        replacement_clock = ManualClock(7)
        replacement_clock.wall_now = clock.wall()
        client = TestClient(create_app(store=Store(path), clock=replacement_clock,
            library=Library(root), backup_root=backup_root, serve_web=False, allow_test_host=True))
        client.get(f"/api/attempts/{aid}")  # recover the process clock independently of the late event
    before = database_row(client, aid)
    svc = client.app.state.services
    answers_before = [dict(r) for r in svc.store.query("SELECT * FROM answers WHERE attempt_id=?", (aid,))]
    response = client.post(f"/api/attempts/{aid}/interrupt", headers=headers(A), json=event)
    assert response.status_code == 200, response.text
    assert response.json()["owner_tab_id"] == B and response.json()["integrity"] == "interrupted"
    assert response.json()["status"] == ("submitted" if closed else "running")
    assert response.json()["timing"]["phase"] == ("finished" if closed else "reading")
    after = database_row(client, aid)
    assert {k: v for k, v in before.items() if k not in ("integrity", "interruptions")} == {
        k: v for k, v in after.items() if k not in ("integrity", "interruptions")}
    assert [dict(r) for r in svc.store.query("SELECT * FROM answers WHERE attempt_id=?", (aid,))] == answers_before
    retry = client.post(f"/api/attempts/{aid}/interrupt", headers=headers(A), json=event)
    assert retry.status_code == 200 and retry.json()["interruptions"] == response.json()["interruptions"]
    assert database_row(client, aid) == after
    altered = client.post(f"/api/attempts/{aid}/interrupt", headers=headers(A),
                          json={**event, "reason": "different_event"})
    assert altered.status_code == 409 and altered.json()["code"] == "interruption_event_conflict"
    for path, method, body in [
        (f"/answers/{reading_q['id']}", "PUT", {"option_id": "D", "revision": 1, "mutation_id": str(uuid.uuid4())}),
        ("/media-state", "PUT", {"queue_index": 0, "position_seconds": 0, "playback_rate": 1}),
        ("/position", "PATCH", {"current_index": 1}),
        ("/claim", "POST", {"takeover": False}),
    ]:
        blocked = client.request(method, f"/api/attempts/{aid}{path}", headers=headers(A), json=body)
        assert blocked.status_code == 409, (path, blocked.text)
    assert database_row(client, aid)["owner_tab_id"] == B
    assert database_row(client, aid)["report"] == before["report"]


def test_never_owner_or_owner_of_other_attempt_cannot_inject_or_ack_event(client, clock):
    svc = client.app.state.services
    other = svc.attempts.create({"exam_ids": ["test-01"], "scope": "reading", "mode": "practice",
        "timer": {"kind": "none"}, "question_filter": "all"})
    svc.attempts.start(other["id"], "other-attempt-owner", True)
    a, event = prepare(client, clock)
    aid = a["id"]
    # A failed non-takeover claim is not proof of ever owning this attempt.
    assert client.post(f"/api/attempts/{aid}/claim", headers=headers("forged"), json={"takeover": False}).status_code == 409
    for token in ("forged", "other-attempt-owner", ""):
        before = database_row(client, aid)
        denied = client.post(f"/api/attempts/{aid}/interrupt", headers=headers(token), json=event)
        assert denied.status_code == 409
        assert database_row(client, aid) == before
    assert client.post(f"/api/attempts/{aid}/interrupt", headers=headers(A), json=event).status_code == 200
    # Knowledge of an already committed event ID grants no ownership proof.
    assert client.post(f"/api/attempts/{aid}/interrupt", headers=headers("forged"), json=event).status_code == 409


def test_concurrent_former_owner_retries_commit_one_event(client, clock):
    a, event = prepare(client, clock)
    url = f"/api/attempts/{a['id']}/interrupt"
    before = database_row(client, a["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(url, headers=headers(A), json=event), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    state = client.get(f"/api/attempts/{a['id']}").json()
    assert sum(e.get("event_id") == event["event_id"] for e in state["interruptions"]) == 1
    assert state["owner_tab_id"] == B and state["timing"]["remaining_ms"] == 4499000
    assert database_row(client, a["id"])["timer"] == before["timer"]


def test_multiple_transfers_retain_each_verified_owner(client, clock):
    a, event = prepare(client, clock)
    aid = a["id"]
    assert client.post(f"/api/attempts/{aid}/claim", headers=headers("third-owner"), json={"takeover": True}).status_code == 200
    for index, token in enumerate((A, B)):
        result = client.post(f"/api/attempts/{aid}/interrupt", headers=headers(token),
            json={**event, "event_id": f"former-owner-event-{index}"})
        assert result.status_code == 200 and result.json()["owner_tab_id"] == "third-owner"
