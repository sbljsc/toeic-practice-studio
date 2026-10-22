"""Application factory: assembles clock, store, library and routers.

Tests inject ManualClock, a TEMP library and a TEMP database through this
factory; the module-level `main.app` uses production defaults.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .attempts import AttemptService
from .backups import BackupService
from .clock import Clock
from .config import PROJECT_ROOT, WEB_DIST, backup_dir, database_url, library_dir
from .errors import ApiError, render_error
from .library import Library
from .store import Store
from .vocabulary import VocabularyService
from .vocab_reference import load_vocab_reference
from .routers import attempts as attempts_router
from .routers import backups as backups_router
from .routers import catalog as catalog_router
from .routers import health as health_router
from .routers import misc as misc_router
from .routers import update as update_router
from .routers import vocabulary as vocabulary_router
from .update_service import UpdateService


class Services:
    def __init__(self, store: Store, library: Library, clock, backup_root: Path,
                 reference=None) -> None:
        self.store = store
        self.library = library
        self.clock = clock
        self.attempts = AttemptService(store, library, clock, reference)
        self.vocabulary = VocabularyService(store, clock, library, reference)
        self.backups = BackupService(store, library, clock, backup_root)
        self.updates = UpdateService()


def create_app(*, clock=None, store=None, library=None, backup_root=None,
               serve_web: bool = True, allow_test_host: bool = False,
               reference=None) -> FastAPI:
    clock = clock or Clock()
    if store is None:
        from sqlalchemy.engine import make_url

        db_path = make_url(database_url()).database or ":memory:"
        store = Store(db_path)
    if library is None:
        library = Library(library_dir())
    library.load()
    if reference is None:
        reference = load_vocab_reference(PROJECT_ROOT)
    services = Services(store, library, clock,
                        Path(backup_root) if backup_root else backup_dir(),
                        reference)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # A release is fetched while the program is idle, so the badge is
        # ready by the time the learner looks at it.
        services.updates.start_idle_check()
        yield

    app = FastAPI(title="TOEIC Practice Local API", version="1.0.0", lifespan=lifespan)
    app.state.services = services
    app.state.allow_test_host = allow_test_host

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return render_error(exc.status_code, exc.detail, exc.code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return render_error(422, "请求格式不正确，请检查字段。", "validation_error")

    app.include_router(health_router.router)
    app.include_router(catalog_router.router)
    app.include_router(attempts_router.router)
    app.include_router(vocabulary_router.router)
    app.include_router(backups_router.router)
    app.include_router(misc_router.router)
    app.include_router(update_router.router)

    @app.get("/api", include_in_schema=False)
    @app.get("/api/{unmatched:path}", include_in_schema=False)
    def unknown_api_route(unmatched: str = "") -> None:
        raise HTTPException(status_code=404, detail="API route not found.")

    if serve_web and WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
