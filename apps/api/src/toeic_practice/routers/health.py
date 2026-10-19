"""Health endpoint for the local API and its store connection."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    svc = request.app.state.services
    svc.store.query("SELECT 1")
    return {"status": "ok", "stage": "backend-v1", "database": "ok"}