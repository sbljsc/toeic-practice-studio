"""The update endpoints: check, download in the background, then install."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..errors import bad_request, unavailable
from ..security import validate_write_request

router = APIRouter(prefix="/api/update", tags=["update"])


def services(request: Request):
    return request.app.state.services


@router.get("/status")
def status(request: Request) -> dict:
    """What the page needs to show: the current phase and the progress."""
    return services(request).updates.snapshot()


@router.post("/check")
def check(request: Request) -> dict:
    """Look for a newer release."""
    validate_write_request(request)
    return services(request).updates.check()


@router.post("/download")
def download(request: Request) -> dict:
    """Start the download in the background."""
    validate_write_request(request)
    try:
        return services(request).updates.start_download()
    except OSError as error:
        raise unavailable(str(error), "update_download_failed") from error


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