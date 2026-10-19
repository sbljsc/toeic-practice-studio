"""Statistics and legacy inventory endpoints."""
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..config import SOURCE_INVENTORY
from ..errors import not_found, unavailable
from ..store import loads

router = APIRouter(prefix="/api", tags=["misc"])


def services(request: Request):
    return request.app.state.services


@router.get("/statistics")
def statistics(request: Request) -> dict:
    svc = services(request)
    rows = svc.store.query(
        "SELECT id, scope, mode, status, integrity, report, created_at FROM attempts "
        "ORDER BY created_at DESC"
    )
    attempt_count = len(rows)
    completed = [r for r in rows if r["status"] in ("submitted", "expired")]
    valid_exams = [r for r in completed if r["mode"] == "exam" and r["integrity"] == "valid"]
    by_part: dict = {}
    for r in valid_exams:
        if not r["report"]:
            continue
        report = loads(r["report"])
        for bucket in report["summary"]["by_part"]:
            b = by_part.setdefault(bucket["part"], {
                "part": bucket["part"], "total": 0, "correct": 0,
                "wrong": 0, "unanswered": 0,
            })
            b["total"] += bucket["total"]
            b["correct"] += bucket["correct"]
            b["wrong"] += bucket["wrong"]
            b["unanswered"] += bucket["unanswered"]
    parts_out = []
    for part in sorted(by_part):
        b = by_part[part]
        b["correct_percent"] = round(100.0 * b["correct"] / b["total"], 1) if b["total"] else 0.0
        parts_out.append(b)
    recent = [
        {"id": r["id"], "scope": r["scope"], "mode": r["mode"],
         "status": r["status"], "integrity": r["integrity"], "created_at": r["created_at"]}
        for r in rows[:10]
    ]
    first = [
        {"id": r["id"], "scope": r["scope"], "mode": r["mode"],
         "status": r["status"], "integrity": r["integrity"], "created_at": r["created_at"]}
        for r in reversed(rows[-10:])
    ] if rows else []
    return {
        "attempt_count": attempt_count,
        "completed_count": len(completed),
        "valid_exam_completed_count": len(valid_exams),
        "practice_completed_count": sum(r["mode"] == "practice" and r["integrity"] == "valid" for r in completed),
        "interrupted_completed_count": sum(r["integrity"] != "valid" for r in completed),
        "by_part": parts_out,
        "first": first,
        "recent": recent,
    }


@router.get("/sources")
def sources(request: Request) -> JSONResponse:
    if services(request).library.pool_mode:
        raise not_found('独立题库不提供来源清单。', 'source_inventory_disabled')
    try:
        inventory = json.loads(SOURCE_INVENTORY.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise unavailable("来源清单缺失。", "inventory_missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise unavailable("来源清单无法解析。", "inventory_invalid") from exc
    return JSONResponse(content=inventory)
