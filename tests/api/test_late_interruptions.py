"""Offline reliability events may arrive after grading; grades remain immutable."""
import uuid

import pytest

from test_review_repairs import HEADERS, TAB, answer, create, start


def row(svc, attempt_id):
    return dict(svc.store.query_one("SELECT * FROM attempts WHERE id=?", (attempt_id,)))


@pytest.mark.parametrize("closure", ["submitted", "expired"])
def test_late_interrupt_updates_reliability_only(client, clock, closure):
    svc = client.app.state.services
    a = create(svc, scope="reading", mode="exam"); start(svc, a)
    answer(svc, a, option="A")
    occurred = round(clock.wall() * 1000)
    if closure == "expired":
        clock.advance(4500)
        before_report = svc.attempts.report(a["id"])
    else:
        before_report = svc.attempts.submit(a["id"], TAB)
    before = row(svc, a["id"])
    before_answers = [dict(r) for r in svc.store.query("SELECT * FROM answers")]
    event = {"reason": "media_failure_queued_offline", "event_id": str(uuid.uuid4()),
             "occurred_at_ms": occurred}
    url = f"/api/attempts/{a['id']}/interrupt"
    response = client.post(url, json=event, headers=HEADERS)
    assert response.status_code == 200
    state = response.json()
    assert state["integrity"] == state["timing"]["integrity"] == "interrupted"
    assert state["status"] == closure and state["timing"]["phase"] == "finished"
    assert state["interruptions"] == [{**event, "wall_ms": round(clock.wall() * 1000)}]
    after = row(svc, a["id"])
    assert {k: v for k, v in after.items() if k not in ("integrity", "interruptions")} == {
        k: v for k, v in before.items() if k not in ("integrity", "interruptions")}
    assert [dict(r) for r in svc.store.query("SELECT * FROM answers")] == before_answers
    clock.advance(10)
    retry = client.post(url, json=event, headers=HEADERS)
    assert retry.status_code == 200 and retry.json()["interruptions"] == state["interruptions"]
    assert row(svc, a["id"]) == after  # lost-ack retry does not even rewrite closed timer checkpoints
    report = client.get(f"/api/attempts/{a['id']}/report").json()
    assert report["attempt"]["integrity"] == "interrupted"
    assert report["attempt"]["interruptions"] == state["interruptions"]
    for key in ("summary", "questions", "groups", "reviews"):
        assert report[key] == before_report[key]
    assert row(svc, a["id"])["report"] == before["report"]
    stats = client.get("/api/statistics").json()
    assert stats["valid_exam_completed_count"] == 0
    assert stats["interrupted_completed_count"] == 1 and stats["by_part"] == []
    assert stats["recent"][0]["integrity"] == "interrupted"
    repeat_submit = client.post(f"/api/attempts/{a['id']}/submit", json={}, headers=HEADERS).json()
    assert repeat_submit["attempt"]["integrity"] == "interrupted"
    assert repeat_submit["summary"] == before_report["summary"]
    # Reliability reporting never reopens the answer or timer capability.
    rejected = client.put(f"/api/attempts/{a['id']}/answers/{a['questions'][0]['id']}",
        json={"option_id": "B", "revision": 1, "mutation_id": str(uuid.uuid4())}, headers=HEADERS)
    assert rejected.status_code == 410
    assert client.post(f"/api/attempts/{a['id']}/continue-practice", json={}, headers=HEADERS).status_code == 410


def test_interrupt_receipt_can_itself_cross_deadline(client, clock):
    svc = client.app.state.services
    a = create(svc, scope="reading", mode="exam"); start(svc, a)
    answer(svc, a, option="A")
    clock.advance(4501)
    response = client.post(f"/api/attempts/{a['id']}/interrupt", json={"reason": "offline_media_failure"}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "expired" and response.json()["integrity"] == "interrupted"
    report = client.get(f"/api/attempts/{a['id']}/report").json()
    assert report["summary"]["correct"] == 1
    assert report["attempt"]["integrity"] == "interrupted"


def test_late_interrupt_event_identity_and_authorization(client):
    svc = client.app.state.services
    a = create(svc); start(svc, a); svc.attempts.submit(a["id"], TAB)
    url = f"/api/attempts/{a['id']}/interrupt"
    event = {"reason": "media_stall", "event_id": "durable-media-event", "occurred_at_ms": 123}
    foreign = {**HEADERS, "X-Tab-ID": "not-the-owner"}
    assert client.post(url, json=event, headers=foreign).status_code == 409
    assert row(svc, a["id"])["integrity"] == "valid"
    assert client.post(url, json=event, headers=HEADERS).status_code == 200
    before = row(svc, a["id"])
    for changed in [{**event, "reason": "different"}, {**event, "occurred_at_ms": 124}]:
        collision = client.post(url, json=changed, headers=HEADERS)
        assert collision.status_code == 409 and collision.json()["code"] == "interruption_event_conflict"
    assert row(svc, a["id"]) == before
    assert client.post(url, json={"reason": "legacy_payload"}, headers=HEADERS).status_code == 200
    assert len(client.get(f"/api/attempts/{a['id']}").json()["interruptions"]) == 2
