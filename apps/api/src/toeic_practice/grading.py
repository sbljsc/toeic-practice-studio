"""Grading: immutable snapshot reports, C/W/U stats, history summary refresh.

build_report runs once at close and is stored verbatim; later library changes
never mutate it. refresh_history_summary re-derives the per-canonical latest
state map used by question filters from all valid closed attempts.
"""

from .clock import now_iso
from .library import READING_PARTS, LISTENING_PARTS
from .store import dumps, loads


def grade(record: dict) -> dict:
    """Pure grading of a closed record against its embedded snapshot keys."""
    summary_by_part: dict = {}
    total = correct = wrong = unanswered = 0
    for q in record["questions"]:
        part = q["part"]
        bucket = summary_by_part.setdefault(
            part, {"part": part, "total": 0, "correct": 0, "wrong": 0, "unanswered": 0}
        )
        bucket["total"] += 1
        total += 1
        selected = record["answers"].get(q["id"], {}).get("option_id")
        if selected is None:
            unanswered += 1
            bucket["unanswered"] += 1
        elif selected == q.get("_answer"):
            correct += 1
            bucket["correct"] += 1
        else:
            wrong += 1
            bucket["wrong"] += 1
    by_part = []
    for part in sorted(summary_by_part):
        b = summary_by_part[part]
        b["correct_percent"] = round(100.0 * b["correct"] / b["total"], 1) if b["total"] else 0.0
        by_part.append(b)
    answered = correct + wrong
    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "unanswered": unanswered,
        "correct_percent": round(100.0 * correct / total, 1) if total else 0.0,
        "wrong_percent": round(100.0 * wrong / total, 1) if total else 0.0,
        "unanswered_percent": round(100.0 * unanswered / total, 1) if total else 0.0,
        "answered_accuracy": round(100.0 * correct / answered, 1) if answered else None,
        "by_part": by_part,
    }


def build_report(record: dict) -> dict:
    """Assemble the private report DTO from the snapshot plus live private keys."""
    questions = []
    groups = []
    for q in record["questions"]:
        selected = record["answers"].get(q["id"], {}).get("option_id")
        answer = q.get("_answer")
        if selected is None:
            result = "unanswered"
        elif selected == answer:
            result = "correct"
        else:
            result = "wrong"
        full = dict(q)
        full.pop("_answer", None)
        full.pop("_explanation", None)
        full["selected_option_id"] = selected
        full["answer"] = answer
        full["explanation"] = q.get("_explanation") or {"text": "", "source_pages": []}
        full["result"] = result
        if q.get("_source_erratum"):
            full["source_erratum"] = q["_source_erratum"]
        if q.get("_source_review_question_number") is not None:
            full["source_review_question_number"] = q["_source_review_question_number"]
        questions.append(full)
    for g in record["groups"]:
        groups.append({k: v for k, v in g.items() if not k.startswith("_")})
    return {
        "attempt": {
            "id": record["id"], "title": record["title"], "scope": record["scope"],
            "mode": record["mode"], "original_mode": record["original_mode"],
            "parts": record["parts"], "exam_ids": record["exam_ids"],
            "status": record["status"], "integrity": record["integrity"],
            "interruptions": record["interruptions"],
            "created_at": record["created_at"], "closed_at": record.get("closed_at"),
            "close_reason": record.get("close_reason"),
            "timer_config": {
                "kind": record["timer"].get("kind", "none"),
                "duration_seconds": record["timer"].get("duration_seconds"),
            },
        },
        "summary": grade(record),
        "questions": questions,
        "groups": groups,
        "reviews": {},
    }


def refresh_history_summary(conn, record: dict) -> None:
    """Update question_latest rows for every canonical id in this attempt."""
    if record["integrity"] != "valid":
        return
    library_version = record["library_version"]
    for q in record["questions"]:
        answer = record["answers"].get(q["id"], {})
        if answer.get("flagged"):
            state = "bookmarked"
        elif answer.get("option_id"):
            state = "correct" if answer["option_id"] == q.get("_answer") else "wrong"
        else:
            state = "unanswered"
        conn.execute(
            "INSERT INTO question_latest(canonical_id, library_version, state, updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(canonical_id, library_version) DO UPDATE SET "
            "state=excluded.state, updated_at=excluded.updated_at",
            (q["canonical_id"], library_version, state, record.get("closed_at") or ""),
        )
