"""The update endpoints: check, download, then install."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..errors import bad_request, unavailable
from ..security import validate_write_request

router = APIRouter(prefix="/api/update", tags=["update"])


def services(request: Request):
    return request.app.state.services


@router.get("/status")
def status(request: Request) -> dict:
    """What release is available, without downloading anything."""
    return services(request).updates.status()


class StageBody(BaseModel):
    pass


@router.post("/stage")
def stage(body: StageBody, request: Request) -> dict:
    """Download the newer release and check its digest."""
    validate_write_request(request)
    try:
        return services(request).updates.stage()
    except OSError as error:
        raise unavailable(str(error), "update_stage_failed") from error


class InstallBody(BaseModel):
    archive: str


@router.post("/install")
def install(body: InstallBody, request: Request) -> dict:
    """Replace the program files once the service stops."""
    validate_write_request(request)
    if not body.archive.strip():
        raise bad_request("请先下载更新包。", "missing_archive")
    try:
        return services(request).updates.install(body.archive)
    except OSError as error:
        raise unavailable(str(error), "update_install_failed") from error