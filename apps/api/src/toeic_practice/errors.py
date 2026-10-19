"""Consistent JSON API errors with readable Chinese messages."""

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    def __init__(self, status_code: int, detail: str, code: str | None = None) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def bad_request(detail: str, code: str = "bad_request") -> ApiError:
    return ApiError(400, detail, code)


def conflict(detail: str, code: str = "conflict") -> ApiError:
    return ApiError(409, detail, code)


def gone(detail: str, code: str = "gone") -> ApiError:
    return ApiError(410, detail, code)


def not_found(detail: str, code: str = "not_found") -> ApiError:
    return ApiError(404, detail, code)


def forbidden(detail: str, code: str = "forbidden") -> ApiError:
    return ApiError(403, detail, code)


def unavailable(detail: str, code: str = "unavailable") -> ApiError:
    return ApiError(503, detail, code)


def render_error(status_code: int, detail: str, code: str | None = None) -> JSONResponse:
    body = {"detail": detail}
    if code:
        body["code"] = code
    return JSONResponse(status_code=status_code, content=body)
