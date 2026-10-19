"""Bounded foreground-question dwell analytics, separate from exam timing.

Clients report a target, never a duration. A lease expires after 15 seconds of
authoritative active elapsed time. Polls/checkpoints settle but cannot renew it.
Unknown/background/statistics spans remain unattributed. No grade keys here.
"""
import uuid

from . import timing

LEASE_MS = 15000


def new_state(coverage="from_start"):
    return {"coverage": coverage, "questions": {}, "session_id": None,
            "sequence": -1, "active": None}


def stop(record):
    state = record.get("activity")
    if state:
        state["active"] = None


def claim(record):
    # Closed historical rows must not acquire invented analytics on inspection.
    if record["status"] in ("submitted", "expired"):
        return
    if record.get("activity") is None:
        record["activity"] = new_state("partial")
        # A legacy answer (including a possibly cleared revised row) may predate
        # measurement. Later clear/reselect must not manufacture a first latency.
        for qid, answer in record.get("answers", {}).items():
            if answer.get("option_id") is not None or answer.get("revision", 0) > 0:
                record["activity"]["questions"][qid] = {
                    "dwell_ms": 0, "first_answer_ms": None, "answer_recorded": True}
    state = record["activity"]
    state.update(session_id=uuid.uuid4().hex, sequence=-1, active=None)


def checkpoint(record, clock):
    state = record.get("activity")
    active = state and state.get("active")
    if not active:
        return
    if (record["status"] != "running" or active["clock_owner"] != clock.identity
            or active["tab_id"] != record["owner_tab_id"]
            or active["phase"] != record["phase"]):
        stop(record)
        return
    end = min(timing.compute_timing(record, clock)["elapsed_ms"], active["lease_until_ms"])
    timer = record["timer"]
    duration = timer.get("phase_durations", {}).get(record["phase"])
    if timer.get("kind") == "countdown" and duration is not None:
        end = min(end, round((float(timer.get("phase_elapsed_before", 0)) + duration) * 1000))
    delta = max(0, end - active["cursor_ms"])
    row = state["questions"].setdefault(active["question_id"],
        {"dwell_ms": 0, "first_answer_ms": None})
    row["dwell_ms"] += delta
    active["cursor_ms"] = max(end, active["cursor_ms"])
    if end >= active["lease_until_ms"]:
        stop(record)


def target(record, clock, qid, sequence):
    state = record["activity"]
    if sequence <= state["sequence"]:
        return  # idempotent/out-of-order requests cannot revive an old target
    state["sequence"] = sequence
    stop(record)
    if qid is not None and record["status"] == "running":
        elapsed = timing.compute_timing(record, clock)["elapsed_ms"]
        state["active"] = {"question_id": qid, "clock_owner": clock.identity,
            "tab_id": record["owner_tab_id"], "phase": record["phase"],
            "cursor_ms": elapsed, "lease_until_ms": elapsed + LEASE_MS}


def first_answer(record, qid, previous, selected):
    state = record.get("activity")
    if not state or previous is not None or selected is None:
        return
    row = state["questions"].setdefault(qid, {"dwell_ms": 0, "first_answer_ms": None})
    if not row.get("answer_recorded"):
        row["answer_recorded"] = True
        # If the question was never observed we do not call an unknown latency 0.
        active = state.get("active")
        observed = row["dwell_ms"] > 0 or (active and active["question_id"] == qid)
        row["first_answer_ms"] = row["dwell_ms"] if observed else None


def summary(record, clock=None):
    state = record.get("activity")
    available = state is not None
    elapsed = (timing.compute_timing(record, clock)["elapsed_ms"] if clock is not None
               else round(float(record["timer"].get("elapsed_before_pause", 0)) * 1000))
    rows, parts = [], {}
    for index, question in enumerate(record["questions"], 1):
        row = state["questions"].get(question["id"], {}) if available else {}
        dwell = row.get("dwell_ms", 0) if available else None
        rows.append({"question_id": question["id"], "number": index, "part": question["part"],
                     "dwell_ms": dwell, "first_answer_ms": row.get("first_answer_ms")})
        part = question["part"]
        if part not in parts:
            parts[part] = 0 if available else None
        if available:
            parts[part] += dwell
    tracked = sum(row["dwell_ms"] or 0 for row in rows)
    return {"coverage": state["coverage"] if available else "unavailable",
        "total_elapsed_ms": elapsed, "tracked_ms": tracked,
        "unattributed_ms": max(0, elapsed - tracked), "questions": rows,
        "parts": [{"part": part, "dwell_ms": parts[part]} for part in sorted(parts)]}
