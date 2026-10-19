"""Server-authoritative timing engine.

State machine: ready -> running -> (paused) -> submitted | expired.
Deadlines are monotonic anchors persisted at start/pause/resume; a restart
re-anchors from the wall-clock checkpoint. Clients never influence the clock.

Phase transitions are anchored to the ORIGINAL phase deadline, never to the
request arrival time: polling delay can never extend the schedule. A request
that arrives after both the listening and reading deadlines have passed
expires the attempt immediately.

Contract semantics (shared with the duration harness):
- elapsed_ms: total elapsed since the attempt first started, excluding paused
  spans (overall, not per-phase).
- remaining_ms: current phase only; null for countup/none timers.
- audio_elapsed_ms: strict listening queue playback progress (exam mode only,
  derived from server elapsed within the listening phase).
"""

READING_EXAM_SECONDS = 4500.0


def checkpoint(record: dict, clock) -> None:
    """Persist elapsed evidence without moving the normal schedule anchors."""
    timer = record["timer"]
    elapsed = float(timer.get("elapsed_before_pause", 0))
    anchor = timer.get("current_phase_started_monotonic")
    if record["status"] == "running" and anchor is not None:
        elapsed += max(0, clock.monotonic() - anchor)
    timer["checkpoint"] = {"owner": clock.identity, "boot": clock.boot_identity,
        "wall": clock.wall(), "monotonic": clock.monotonic(), "elapsed": elapsed}


def recover(record: dict, clock) -> None:
    """Re-anchor only after owner change; wall rollback cannot grant extra time.

    Across process/boot boundaries offline elapsed is inherently uncertain. Keep
    the durable elapsed floor, charge forward wall time, and fail closed for a
    backwards wall clock. Every recovered live attempt is interrupted.
    """
    if record["status"] not in ("running", "paused"):
        return
    timer = record["timer"]
    saved = timer.get("checkpoint")
    if saved and saved["owner"] == clock.identity:
        if record["status"] == "running":
            wall_delta = clock.wall() - saved["wall"]
            mono_delta = clock.monotonic() - saved["monotonic"]
            if abs(wall_delta - mono_delta) > 2:
                # This process still owns its monotonic anchor. A wall-clock
                # adjustment is reliability evidence, never elapsed exam time.
                # Reproject only the display UTC deadline onto the changed wall
                # clock; keep overshoot (including a negative remaining span).
                duration = _phase_deadline(timer, record["phase"])
                anchor = timer.get("current_phase_started_monotonic")
                if duration is not None and anchor is not None:
                    phase_elapsed = (clock.monotonic() - anchor +
                        float(timer.get("elapsed_before_pause", 0)) -
                        float(timer.get("phase_elapsed_before", 0)))
                    timer["current_phase_deadline_wall"] = clock.wall() + duration - phase_elapsed
                mark_interrupted(record, clock, "clock_discontinuity")
        return
    mark_interrupted(record, clock, "server_restart")
    if record["status"] == "running":
        if saved:
            offline = clock.wall() - saved["wall"]
            elapsed = max(float(timer.get("elapsed_before_pause", 0)), saved["elapsed"])
            if offline < 0:
                elapsed = max(elapsed, sum(timer.get("phase_durations", {}).values()))
            else:
                elapsed += offline
        else:
            # Legacy rows have no trustworthy monotonic owner. Use the original
            # wall deadline if present, never project their foreign mono value.
            duration = _phase_deadline(timer, record["phase"])
            deadline = timer.get("current_phase_deadline_wall")
            phase_elapsed = max(0, duration - (deadline - clock.wall())) if duration is not None and deadline is not None else 0
            elapsed = max(float(timer.get("elapsed_before_pause", 0)),
                          float(timer.get("phase_elapsed_before", 0)) + phase_elapsed)
        phase_before = float(timer.get("phase_elapsed_before", 0))
        timer["elapsed_before_pause"] = phase_before
        timer["current_phase_started_monotonic"] = clock.monotonic() - (elapsed - phase_before)
    checkpoint(record, clock)


def _phase_deadline(timer: dict, phase: str) -> float | None:
    if timer.get("kind") != "countdown":
        return None
    return timer.get("phase_durations", {}).get(phase)


def compute_timing(record: dict, clock) -> dict:
    """Pure projection of persisted timer state; never mutates the record."""
    timer = record["timer"]
    phase = record["phase"]
    kind = timer.get("kind", "none")
    elapsed = float(timer.get("elapsed_before_pause", 0.0))
    if record["status"] == "running" and timer.get("current_phase_started_monotonic") is not None:
        elapsed += max(0.0, clock.monotonic() - timer["current_phase_started_monotonic"])

    phase_elapsed = elapsed - float(timer.get("phase_elapsed_before", 0.0))
    duration = _phase_deadline(timer, phase)
    remaining_ms = None
    if kind == "countdown" and duration is not None and record["status"] in ("running", "paused"):
        remaining_ms = max(0, round((duration - phase_elapsed) * 1000))

    audio_elapsed_ms = 0
    if record["status"] in ("running", "paused") and phase == "listening" and record["mode"] == "exam":
        audio_elapsed_ms = max(0, round(phase_elapsed * 1000))

    deadline_at_ms = None
    if kind == "countdown" and duration is not None and record["status"] in ("running", "paused"):
        anchor_wall = timer.get("current_phase_deadline_wall")
        if anchor_wall is not None:
            deadline_at_ms = round(anchor_wall * 1000)

    return {
        "kind": kind,
        "phase": phase,
        "remaining_ms": remaining_ms,
        "elapsed_ms": round(elapsed * 1000),
        "server_time_ms": round(clock.wall() * 1000),
        "deadline_at_ms": deadline_at_ms,
        "can_pause": record["mode"] == "practice" and record["status"] in ("running", "paused"),
        "is_paused": record["status"] == "paused",
        "integrity": record["integrity"],
        "phase_question_ids": record.get("phase_question_ids", {}).get(phase, []),
    }


def _accumulate(record: dict, clock) -> None:
    """Fold the in-flight running span into elapsed_before_pause."""
    timer = record["timer"]
    if timer.get("current_phase_started_monotonic") is not None and record["status"] == "running":
        timer["elapsed_before_pause"] = float(timer.get("elapsed_before_pause", 0.0)) + max(
            0.0, clock.monotonic() - timer["current_phase_started_monotonic"]
        )
        timer["current_phase_started_monotonic"] = None


def _start_phase(record: dict, clock, phase: str) -> None:
    timer = record["timer"]
    record["phase"] = phase
    timer["phase_elapsed_before"] = float(timer.get("elapsed_before_pause", 0.0))
    timer["current_phase_started_monotonic"] = clock.monotonic()
    duration = _phase_deadline(timer, phase)
    timer["current_phase_deadline_wall"] = clock.wall() + duration if duration is not None else None


def _phase_start_monotonic(timer: dict) -> float | None:
    """Monotonic anchor of the current running phase."""
    return timer.get("current_phase_started_monotonic")


def advance(record: dict, clock) -> str | None:
    """Advance phase/status when a countdown deadline passed.

    Returns "listening_finished" / "expired" / None. The caller persists the
    mutated record inside its transaction.

    The transition loop is anchored to each phase's ORIGINAL deadline:
    overshoot carries into the next phase, so a request delayed past the
    listening deadline shortens reading by exactly the overshoot, and a
    request delayed past both deadlines expires immediately.
    """
    if record["status"] != "running":
        return None
    timer = record["timer"]
    if timer.get("kind") != "countdown":
        return None
    if _phase_start_monotonic(timer) is None:
        return None

    transition: str | None = None
    while True:
        phase = record["phase"]
        duration = _phase_deadline(timer, phase)
        if duration is None:
            return transition
        anchor = _phase_start_monotonic(timer)
        phase_elapsed = (clock.monotonic() - anchor) + (
            float(timer.get("elapsed_before_pause", 0.0))
            - float(timer.get("phase_elapsed_before", 0.0))
        )
        if phase_elapsed < duration:
            return transition

        phases = timer.get("phases", [phase])
        idx = phases.index(phase)
        # Fold elapsed up to the ORIGINAL deadline (not "now") so overshoot
        # is carried into the next phase instead of extending it.
        overshoot = phase_elapsed - duration
        timer["elapsed_before_pause"] = (
            float(timer.get("phase_elapsed_before", 0.0)) + duration
        )
        timer["current_phase_started_monotonic"] = None

        if phase == "listening" and idx + 1 < len(phases) and phases[idx + 1] == "reading":
            transition = transition or "listening_finished"
            record["phase"] = "reading"
            timer["phase_elapsed_before"] = float(timer["elapsed_before_pause"])
            # Anchor reading at the original listening deadline; elapsed so
            # far in the reading phase equals the overshoot.
            timer["current_phase_started_monotonic"] = anchor + duration
            reading_duration = _phase_deadline(timer, "reading")
            # The reading phase starts at the original listening deadline;
            # extend that wall anchor by the full reading duration so polling
            # delay never grants extra time.
            listening_deadline_wall = timer.get("current_phase_deadline_wall")
            if listening_deadline_wall is not None and reading_duration is not None:
                timer["current_phase_deadline_wall"] = listening_deadline_wall + reading_duration
            elif reading_duration is not None:
                timer["current_phase_deadline_wall"] = clock.wall() + max(
                    0.0, reading_duration - overshoot
                )
            continue

        record["status"] = "expired"
        record["phase"] = "finished"
        timer["finished_at_monotonic"] = anchor + duration
        timer["elapsed_before_pause"] = (
            float(timer.get("phase_elapsed_before", 0.0)) + duration
        )
        timer["current_phase_started_monotonic"] = None
        # Final expiry dominates: even when this same call also crossed the
        # listening boundary, the attempt must be graded and closed now.
        return "expired"


def start(record: dict, clock) -> None:
    """Begin the attempt clock. Idempotent: a second start never resets."""
    if record["status"] != "ready":
        return
    record["timer"]["elapsed_before_pause"] = 0.0
    record["timer"]["phase_elapsed_before"] = 0.0
    record["status"] = "running"
    _start_phase(record, clock, record["phase"])


def pause(record: dict, clock) -> None:
    if record["status"] != "running" or record["mode"] != "practice":
        return
    _accumulate(record, clock)
    record["status"] = "paused"
    timer = record["timer"]
    duration = _phase_deadline(timer, record["phase"])
    if duration is not None:
        phase_elapsed = float(timer.get("elapsed_before_pause", 0.0)) - float(
            timer.get("phase_elapsed_before", 0.0)
        )
        timer["current_phase_deadline_wall"] = clock.wall() + max(0.0, duration - phase_elapsed)


def resume(record: dict, clock) -> None:
    if record["status"] != "paused":
        return
    record["status"] = "running"
    timer = record["timer"]
    timer["current_phase_started_monotonic"] = clock.monotonic()
    # Refresh the wall deadline from the remaining time at resume rather than
    # keeping the pause-time wall anchor (which would sit in the past).
    duration = _phase_deadline(timer, record["phase"])
    if duration is not None:
        phase_elapsed = float(timer.get("elapsed_before_pause", 0.0)) - float(
            timer.get("phase_elapsed_before", 0.0)
        )
        timer["current_phase_deadline_wall"] = clock.wall() + max(0.0, duration - phase_elapsed)

    # Resumed practice retains the elapsed phase offset in its anchor so the
    # unchanged advance loop also carries overshoot after exam conversion.
    phase_before = float(timer.get("phase_elapsed_before", 0.0))
    phase_elapsed = float(timer.get("elapsed_before_pause", 0.0)) - phase_before
    timer["current_phase_started_monotonic"] = clock.monotonic() - phase_elapsed
    timer["elapsed_before_pause"] = phase_before


def mark_interrupted(record: dict, clock, reason: str, *, event_id: str | None = None,
                     occurred_at_ms: int | None = None) -> bool:
    """Reliability is append-only even after close; never alter time or grades.

    occurred_at_ms is untrusted client event metadata, not a deadline input.
    wall_ms records server receipt. An acknowledged event can be retried safely.
    """
    if event_id is not None:
        for event in record.get("interruptions", []):
            if event.get("event_id") == event_id:
                if event["reason"] != reason or event.get("occurred_at_ms") != occurred_at_ms:
                    from .errors import conflict
                    raise conflict("中断事件标识已被其他事件使用。", "interruption_event_conflict")
                return False
    event = {"reason": reason, "wall_ms": round(clock.wall() * 1000)}
    if event_id is not None:
        event["event_id"] = event_id
    if occurred_at_ms is not None:
        event["occurred_at_ms"] = occurred_at_ms
    record["integrity"] = "interrupted"
    record.setdefault("interruptions", []).append(event)
    return True


def make_timer(kind: str, duration_seconds: float | None, phases: list,
               phase_durations: dict) -> dict:
    return {
        "kind": kind,
        "duration_seconds": duration_seconds,
        "phases": phases,
        "phase_durations": phase_durations,
        "elapsed_before_pause": 0.0,
        "phase_elapsed_before": 0.0,
        "current_phase_started_monotonic": None,
        "current_phase_deadline_wall": None,
    }
