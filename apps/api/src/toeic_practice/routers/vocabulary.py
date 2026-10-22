"""Vocabulary and settings HTTP boundary."""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..errors import bad_request, unavailable
from ..security import validate_write_request

router = APIRouter(prefix="/api", tags=["vocabulary"])


def services(request: Request):
    return request.app.state.services


@router.get("/vocabulary")
def vocabulary(request: Request) -> dict:
    svc = services(request)
    return svc.vocabulary.list_entries(current_library_version=svc.library.library_version())


@router.get("/vocabulary/reference")
def vocabulary_reference(request: Request, q: str = "", limit: int = 20) -> dict:
    """Look up reference material for one word, or search for words."""
    svc = services(request)
    reference = svc.vocabulary.reference
    if reference is None or not reference.available:
        raise unavailable("词汇参考数据不可用。", "reference_unavailable")
    query = (q or "").strip()
    if not query:
        raise bad_request("请输入要查询的单词。", "missing_query")
    limit = max(1, min(int(limit), 50))
    from ..vocab_reference import reference_entry
    exact = reference_entry(reference, query)
    if exact is not None and len(query.split()) == 1:
        return {"query": query, "exact": exact, "matches": [], "source": reference.source}
    matches = [reference_entry(reference, entry['word'])
               for entry in reference.search(query, limit)]
    return {"query": query, "exact": None, "matches": matches, "source": reference.source}


class VocabularyPatch(BaseModel):
    mastered: bool | None = None
    manual_required: bool | None = None


@router.patch("/vocabulary/{entry_id:path}")
def patch_vocabulary(entry_id: str, body: VocabularyPatch, request: Request) -> dict:
    validate_write_request(request)
    return services(request).vocabulary.patch_entry(entry_id, body.model_dump(exclude_none=True))


class SettingsPatch(BaseModel):
    vocabulary_threshold: int | None = None


@router.get("/settings")
def get_settings(request: Request) -> dict:
    svc = services(request)
    row = svc.store.query_one("SELECT value FROM settings WHERE key='vocabulary_threshold'")
    return {"vocabulary_threshold": int(row["value"]) if row else 3}


@router.patch("/settings")
def patch_settings(body: SettingsPatch, request: Request) -> dict:
    validate_write_request(request)
    if body.vocabulary_threshold is None or not 1 <= body.vocabulary_threshold <= 20:
        raise bad_request("词汇阈值必须在 1..20 之间。", "bad_threshold")
    svc = services(request)
    with svc.store.transaction() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('vocabulary_threshold', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(body.vocabulary_threshold),),
        )
    return {"vocabulary_threshold": body.vocabulary_threshold}
