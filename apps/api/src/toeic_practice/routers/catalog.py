"""Library catalog: exams, groups, registered assets with Range support."""
from functools import wraps
from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse

from ..errors import not_found, unavailable
from ..library import LISTENING_PARTS

router = APIRouter(prefix="/api", tags=["catalog"])


def services(request: Request):
    return request.app.state.services


def library_read(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with services(kwargs["request"]).store.exclusive():
            return function(*args, **kwargs)
    return guarded


def _require_library(request: Request):
    library = services(request).library
    if not library.available:
        raise unavailable(f"内置题库不可用：{library.load_error}", "library_unavailable")
    return library


@router.get("/question-pool")
@library_read
def question_pool(request: Request) -> dict:
    from ..pool_library import catalog
    return catalog(_require_library(request))


@router.get('/question-pool/status')
@library_read
def question_pool_status(request: Request,response: Response) -> dict:
    from ..pool_status import current_status
    response.headers['Cache-Control']='no-store'
    return current_status(services(request).attempts)


@router.get('/question-pool/questions/{qid}')
@library_read
def question_pool_detail(qid: str,request: Request,response: Response,include_solution: bool=False) -> dict:
    from ..pool_status import question_detail
    response.headers['Cache-Control']='no-store'
    return question_detail(services(request).attempts,qid,include_solution)


@router.get("/exams")
@library_read
def exams(request: Request) -> dict:
    library = _require_library(request)
    out = []
    for exam in library.exams.values():
        parts = []
        counts = {p: 0 for p in range(1, 8)}
        for q in exam.questions:
            counts[q["part"]] = counts.get(q["part"], 0) + 1
        for part in range(1, 8):
            ready = exam.exam_ready_reason(exam) if hasattr(exam, "exam_ready_reason") else None
            reason = library.exam_ready_reason(exam)
            entry = {
                "part": part,
                "section": "listening" if part in LISTENING_PARTS else "reading",
                "count": counts.get(part, 0),
                "ready": reason is None,
            }
            if reason is not None:
                entry["reason"] = reason
            parts.append(entry)
        reason = library.exam_ready_reason(exam)
        item = {
            "id": exam.id,
            "title": exam.title,
            "version": exam.version,
            "question_count": exam.question_count,
            "parts": parts,
            "audio_duration_seconds": (exam.audio or {}).get("duration_seconds"),
            "exam_audio_duration_seconds": exam.listening_seconds,
            "ready": reason is None,
        }
        if reason is not None:
            item["reason"] = reason
        out.append(item)
    return {"library_version": library.library_version(), "exams": out}


@router.get("/exams/{exam_id}/groups")
@library_read
def groups(exam_id: str, request: Request) -> dict:
    library = _require_library(request)
    exam = library.exams.get(exam_id)
    if exam is None:
        raise not_found("试卷不存在。", "exam_not_found")
    reason = library.exam_ready_reason(exam)
    out = []
    for group in exam.groups:
        cue = library.group_cue_for(exam, group)
        group_ready = reason is None
        group_reason = reason
        if group["section"] == "listening" and cue is None:
            group_ready = False
            group_reason = "该题组的音频时间轴尚未就绪"
        item = {
            "id": group["id"],
            "part": group["part"],
            "section": group["section"],
            "question_ids": list(group.get("question_ids", [])),
            "numbers": sorted(
                q["number"] for q in exam.questions if q["id"] in set(group.get("question_ids", []))
            ),
            "ready": group_ready,
        }
        if group_reason:
            item["reason"] = group_reason
        out.append(item)
    return {"groups": out}


@router.get("/assets/{asset_id}")
@library_read
def asset(asset_id: str, request: Request):
    library = _require_library(request)
    try:
        path, media_type = library.asset_path(asset_id)
    except KeyError:
        raise not_found("资产未登记。", "asset_not_found")
    except FileNotFoundError:
        raise unavailable("资产文件缺失。", "asset_missing")
    return FileResponse(path, media_type=media_type)
