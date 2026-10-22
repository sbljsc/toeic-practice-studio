"""The update endpoints: check, download in the background, then install."""
from __future__ import annotations

import threading

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


@router.post("/shutdown")
def shutdown(request: Request) -> dict:
    """Stop the service so the program files can be replaced.

    The database is closed first, so the learner's records are written
    out properly. The process then ends, because the program files
    cannot be replaced while it still holds them open.
    """
    validate_write_request(request)
    services(request).store.close()
    # The process has to end too: the program files cannot be replaced
    # while it still holds them open.
    threading.Thread(target=_stop_process, daemon=True).start()
    return {"stopping": True}


def _stop_process() -> None:
    """Ask the server to stop, then end the process if it does not."""
    import os
    import time

    from .. import launcher
    launcher.request_stop()
    for _ in range(40):
        if launcher.RUNNING_SERVER is None or not launcher.RUNNING_SERVER.started:
            break
        time.sleep(0.25)
    os._exit(0)


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