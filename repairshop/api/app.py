"""The one FastAPI application: API routes, the built React app and background work.

Run it as exactly one process. SQLite is the database, and a second worker process
would not share the in-memory sessions or the single background loop. See
ARCHITECTURE.md ("Deployment") before changing this.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from repairshop.persistence import Database
from . import errors, spa
from .config import Config
from .scheduler import Scheduler
from .sessions import Sessions, CSRF_HEADER, CSRF_VALUE
from .modules import ROUTERS

SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


@dataclass
class Runtime:
    config: Config
    db: Database
    sessions: Sessions
    scheduler: Scheduler | None = None
    server: object = None


def create_app(config: Config, db: Database | None = None) -> FastAPI:
    database = db or Database(config.data_dir)
    runtime = Runtime(config=config, db=database, sessions=Sessions(config.session_idle_seconds))
    runtime.scheduler = Scheduler(runtime, config.scheduler_interval)

    @asynccontextmanager
    async def lifespan(app):
        if config.scheduler:
            runtime.scheduler.start()
        try:
            yield
        finally:
            await runtime.scheduler.stop()
            database.engine.dispose()

    app = FastAPI(title='RepairShop Manager', version=_version(), lifespan=lifespan,
                  docs_url='/api/docs', openapi_url='/api/openapi.json', redoc_url=None)
    app.state.runtime = runtime
    errors.install(app)

    @app.middleware('http')
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith('/api/') and request.method not in SAFE_METHODS \
                and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return JSONResponse(errors.body('CSRF_REJECTED', 'This request did not come from the RepairShop application.'),
                                status_code=403)
        response = await call_next(request)
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        if path.startswith('/api/'):
            response.headers.setdefault('Cache-Control', 'no-store')
        return response

    for router in ROUTERS:
        app.include_router(router, prefix='/api')
    spa.install(app, config.frontend_dist)
    return app


def _version():
    try:
        from importlib.metadata import version
        return version('repairshop-manager')
    except Exception:
        return 'development'
