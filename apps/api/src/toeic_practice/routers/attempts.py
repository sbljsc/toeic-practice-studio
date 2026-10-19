"""Attempt HTTP boundary. All domain rules live in AttemptService."""
from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from ..security import validate_write_request

router = APIRouter(prefix="/api", tags=["attempts"])


def services(request: Request):
    return request.app.state.services


class TimerRequest(BaseModel):
    kind: str = "none"
    duration_seconds: float | None = None


class CreateAttemptRequest(BaseModel):
    exam_ids: list[str] = Field(default_factory=list)
    scope: str = "reading"
    parts: list[int] = Field(default_factory=list)
    mode: str = "practice"
    timer: TimerRequest = Field(default_factory=TimerRequest)
    question_filter: str = "all"
    group_ids: list[str] = Field(default_factory=list)
    random: dict | None = None
    retake_attempt_id: str | None = Field(default=None, max_length=128)
    selection_preference: str = 'unanswered_first'


class ClaimRequest(BaseModel):
    takeover: bool = False


class StartRequest(BaseModel):
    media_ready: bool = False


class InterruptRequest(BaseModel):
    reason: str = Field(default="", max_length=2048)
    event_id: str | None = Field(default=None, min_length=1, max_length=128)
    occurred_at_ms: int | None = Field(default=None, ge=0)


class MediaStateRequest(BaseModel):
    queue_index: int = 0
    position_seconds: float = 0.0
    playback_rate: float = 1.0


class PositionRequest(BaseModel):
    current_index: int = 0


class AnswerRequest(BaseModel):
    option_id: str | None = None
    flagged: bool | None = None
    visited: bool | None = None
    revision: int = 0
    mutation_id: str = ""


class ReviewWord(BaseModel):
    term: str = ""
    sense: str = ""
    modality: str = "meaning"
    causal: bool = False


class ReviewRequest(BaseModel):
    causes: list[str] = Field(default_factory=list)
    words: list[ReviewWord] = Field(default_factory=list)


@router.post("/attempts")
def create_attempt(body: CreateAttemptRequest, request: Request) -> dict:
    validate_write_request(request)
    return services(request).attempts.create(body.model_dump())


@router.get("/attempts")
def list_attempts(request: Request) -> dict:
    return {"attempts": services(request).attempts.list()}


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str, request: Request) -> dict:
    return services(request).attempts.get(attempt_id)


@router.get("/attempts/{attempt_id}/clock")
def attempt_clock(attempt_id: str, request: Request) -> dict:
    return services(request).attempts.clock_state(attempt_id)


@router.post("/attempts/{attempt_id}/claim")
def claim_attempt(attempt_id: str, body: ClaimRequest, request: Request,
                  x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    if not x_tab_id:
        from ..errors import bad_request
        raise bad_request("缺少 X-Tab-ID。", "tab_id_required")
    return services(request).attempts.claim(attempt_id, x_tab_id, body.takeover)


@router.post("/attempts/{attempt_id}/start")
def start_attempt(attempt_id: str, body: StartRequest, request: Request,
                  x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.start(attempt_id, x_tab_id, body.media_ready)


@router.post("/attempts/{attempt_id}/pause")
def pause_attempt(attempt_id: str, request: Request,
                  x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.pause(attempt_id, x_tab_id)


@router.post("/attempts/{attempt_id}/resume")
def resume_attempt(attempt_id: str, request: Request,
                   x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.resume(attempt_id, x_tab_id)


@router.post("/attempts/{attempt_id}/interrupt")
def interrupt_attempt(attempt_id: str, body: InterruptRequest, request: Request,
                      x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.interrupt(attempt_id, x_tab_id, body.reason,
        event_id=body.event_id, occurred_at_ms=body.occurred_at_ms)


@router.post("/attempts/{attempt_id}/continue-practice")
def continue_practice(attempt_id: str, request: Request,
                      x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.continue_practice(attempt_id, x_tab_id)


@router.put("/attempts/{attempt_id}/media-state")
def put_media_state(attempt_id: str, body: MediaStateRequest, request: Request,
                    x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.set_media_state(attempt_id, x_tab_id, body.model_dump())


@router.patch("/attempts/{attempt_id}/position")
def patch_position(attempt_id: str, body: PositionRequest, request: Request,
                   x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.set_position(attempt_id, x_tab_id, body.current_index)


@router.put("/attempts/{attempt_id}/answers/{qid}")
def put_answer(attempt_id: str, qid: str, body: AnswerRequest, request: Request,
               x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.put_answer(
        attempt_id, qid, x_tab_id, body.model_dump(exclude_none=True)
    )


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(attempt_id: str, request: Request,
                   x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.submit(attempt_id, x_tab_id)


@router.get("/attempts/{attempt_id}/report")
def attempt_report(attempt_id: str, request: Request) -> dict:
    return services(request).attempts.report(attempt_id)


@router.put("/attempts/{attempt_id}/reviews/{qid}")
def put_review(attempt_id: str, qid: str, body: ReviewRequest, request: Request,
               x_tab_id: str | None = Header(default=None)) -> dict:
    validate_write_request(request)
    return services(request).attempts.put_review(attempt_id, qid, body.model_dump())


@router.get("/attempts/{attempt_id}/candidates/{qid}")
def candidates(attempt_id: str, qid: str, request: Request) -> dict:
    return services(request).attempts.candidates(attempt_id, qid)
