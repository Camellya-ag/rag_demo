"""Central router registration (pattern from base_fastapi_ai)."""

from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.config import API_PREFIX


def register_routers(app: FastAPI) -> None:
    app.include_router(router)
