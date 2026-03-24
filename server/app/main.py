from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.admin_router import router as admin_router
from app.api.auth_router import router as auth_router
from app.api.client_api_router import router as client_api_router
from app.api.dashboard_router import router as dashboard_router
from app.api.owner_router import router as owner_router
from app.api.public_router import router as public_router
from app.api.tester_router import router as tester_router
from app.db.base import Base
from app.db.session import SessionLocal
from app.db.session import engine
from app.db import models  # noqa: F401
from app.services.client_task_service import start_client_task_worker
from app.services.client_task_service import stop_client_task_worker
from app.services.leaderboard_service import LeaderboardRefreshThread
from app.services.seed_service import ensure_admin
from app.services.seed_service import ensure_roles
from app.services.schema_service import ensure_schema
from app.settings import get_settings


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.state.client_task_worker = None
app.state.leaderboard_thread = None
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(public_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(tester_router)
app.include_router(owner_router)
app.include_router(admin_router)
app.include_router(client_api_router)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    db = SessionLocal()
    try:
        ensure_roles(db)
        ensure_admin(db)
    finally:
        db.close()
    app.state.client_task_worker = start_client_task_worker()
    leaderboard_thread = LeaderboardRefreshThread()
    leaderboard_thread.start()
    app.state.leaderboard_thread = leaderboard_thread


@app.on_event("shutdown")
def shutdown() -> None:
    client_worker = getattr(app.state, "client_task_worker", None)
    if client_worker is not None:
        stop_client_task_worker()
        app.state.client_task_worker = None
    leaderboard_thread = getattr(app.state, "leaderboard_thread", None)
    if leaderboard_thread is not None:
        leaderboard_thread.stop()
        leaderboard_thread.join(timeout=2)
        app.state.leaderboard_thread = None
