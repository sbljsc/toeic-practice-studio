"""Backup HTTP boundary."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..security import validate_write_request

router = APIRouter(prefix="/api/backups", tags=["backups"])


def services(request: Request):
    return request.app.state.services


class CreateBackup(BaseModel):
    include_library: bool = False


class RestoreBackup(BaseModel):
    confirm: bool = False


@router.get("")
def list_backups(request: Request) -> dict:
    return services(request).backups.list_backups()


@router.post("")
def create_backup(body: CreateBackup, request: Request) -> dict:
    validate_write_request(request)
    return services(request).backups.create(body.include_library)


@router.get("/{backup_id}/download")
def download_backup(backup_id: str, request: Request):
    path = services(request).backups.file_for_download(backup_id)
    return FileResponse(path, media_type="application/octet-stream",
                        filename=path.name)


@router.post("/{backup_id}/restore")
def restore_backup(backup_id: str, body: RestoreBackup, request: Request) -> dict:
    validate_write_request(request)
    return services(request).backups.restore(backup_id, body.confirm)
