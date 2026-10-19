"""Fake-clock timing tests: deadline anchoring, overshoot carry, expiry,
pause/resume deadline refresh, restart re-anchor. No wall-clock sleeps."""
import uuid

import pytest

from toeic_practice import timing
from toeic_practice.attempts import AttemptService
from toeic_practice.clock import ManualClock, now_iso


def make_service(tmp_path, clock, library):
    from toeic_practice.store import Store
    store = Store(tmp_path / "timing.sqlite3")
    library.load()
    return AttemptService(store, library, clock)


def create_full(svc, mode="exam", timer_kind="none"):
    return svc.create({
        "exam_ids": ["test-01"], "scope": "full", "mode": mode,
        "timer": {"kind": timer_kind}, "question_filter": "all",
    })


def test_full_exam_forces_countdown_even_if_request_says_none(tmp_path, clock, library):
    svc = make_service(tmp_path, clock, library)
    attempt = svc.create({
        "exam_ids": ["test-01"], "scope": "full", "mode": "exam",
        "timer": {"kind": "none"}, "question_filter": "all",
    })
    assert attempt["timing"]["kind"] == "countdown"
    svc.claim(attempt["id"], "tab-1", False)
    svc.start(attempt["id"], "tab-1", True)
    state = svc.clock_state(attempt["id"])
    assert state["timing"]["phase"] == "listening"
    # listening deadline equals fixture audio duration 120s
    assert state["timing"]["remaining_ms"] == pytest.approx(120000, abs=500)


def test_delayed_poll_carries_overshoot_into_reading(tmp_path, clock, library):
    svc = make_service(tmp_path, clock, library)
    attempt = create_full(svc)
    svc.claim(attempt["id"], "tab-1", False)
    svc.start(attempt["id"], "tab-1", True)
    clock.advance(121.0)  # 1s past the 120s listening deadline
    state = svc.clock_state(attempt["id"])
    assert state["timing"]["phase"] == "reading"
    assert state["status"] == "running"
    # reading got the overshoot deducted: 4500 - 1 seconds
    assert state["timing"]["remaining_ms"] == pytest.approx(4499000, abs=200)


def test_poll_beyond_both_phases_expires_immediately(tmp_path, clock, library):
    svc = make_service(tmp_path, clock, library)
    attempt = create_full(svc)
    svc.claim(attempt["id"], "tab-1", False)
    svc.start(attempt["id"], "tab-1", True)
    clock.advance(120.0 + 4500.0 + 1.0)
    state = svc.clock_state(attempt["id"])
    assert state["status"] == "expired"
    assert state["timing"]["phase"] == "finished"
    report = svc.report(attempt["id"])
    assert report["summary"]["total"] == 200
    assert report["summary"]["unanswered"] == 200


def test_no_extra_time_from_polling(tmp_path, clock, library):
    svc = make_service(tmp_path, clock, library)
    attempt = create_full(svc)
    svc.claim(attempt["id"], "tab-1", False)
    svc.start(attempt["id"], "tab-1", True)
    clock.advance(119.0)
    svc.clock_state(attempt["id"])  # poll right before the deadline
    clock.advance(2.0)  # 1s past
    state = svc.clock_state(attempt["id"])
    assert state["timing"]["phase"] == "reading"
    assert state["timing"]["remaining_ms"] == pytest.approx(4499000, abs=200)


def test_pause_freezes_and_resume_refreshes_deadline(tmp_path, clock, library):
    svc = make_service(tmp_path, clock, library)
    attempt = svc.create({
        "exam_ids": ["test-01"], "scope": "part", "parts": [5], "mode": "practice",
        "timer": {"kind": "countdown", "duration_seconds": 60}, "question_filter": "all",
    })
    svc.claim(attempt["id"], "tab-1", False)
    svc.start(attempt["id"], "tab-1", True)
    clock.advance(20)
    paused = svc.pause(attempt["id"], "tab-1")
    assert paused["timing"]["is_paused"]
    remaining_at_pause = paused["timing"]["remaining_ms"]
    assert remaining_at_pause == pytest.approx(40000, abs=300)
    clock.advance(9999)  # paused: time must not move
    still = svc.clock_state(attempt["id"])
    assert still["status"] == "paused"
    assert still["timing"]["remaining_ms"] == remaining_at_pause
    resumed = svc.resume(attempt["id"], "tab-1")
    assert resumed["timing"]["deadline_at_ms"] == pytest.approx(
        (clock.wall() + 40.0) * 1000, abs=200)
    clock.advance(41)
    expired = svc.clock_state(attempt["id"])
    assert expired["status"] == "expired"


def test_restart_reanchors_from_checkpoint(tmp_path, library):
    clock_a = ManualClock()
    svc_a = make_service(tmp_path, clock_a, library)
    attempt = svc_a.create({
        "exam_ids": ["test-01"], "scope": "part", "parts": [5], "mode": "practice",
        "timer": {"kind": "countdown", "duration_seconds": 60}, "question_filter": "all",
    })
    svc_a.claim(attempt["id"], "tab-1", False)
    svc_a.start(attempt["id"], "tab-1", True)
    clock_a.advance(10)
    svc_a.pause(attempt["id"], "tab-1")

    # Simulate restart: new clock with different monotonic base, same wall.
    clock_b = ManualClock(start=9_000_000.0)
    clock_b.wall_now = clock_a.wall_now
    svc_b = make_service(tmp_path, clock_b, library)
    state = svc_b.clock_state(attempt["id"])
    assert state["status"] == "paused"
    assert state["timing"]["remaining_ms"] == pytest.approx(50000, abs=300)


def test_elapsed_ms_is_whole_attempt_across_phases(tmp_path, clock, library):
    svc = make_service(tmp_path, clock, library)
    attempt = create_full(svc)
    svc.claim(attempt["id"], "tab-1", False)
    svc.start(attempt["id"], "tab-1", True)
    clock.advance(120.5)
    state = svc.clock_state(attempt["id"])
    assert state["timing"]["phase"] == "reading"
    # elapsed includes the whole listening phase plus reading overshoot
    assert state["timing"]["elapsed_ms"] == pytest.approx(120500, abs=300)