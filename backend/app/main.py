from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import CORS_ORIGINS
from backend.app.core.exceptions.handlers import register_exception_handlers
from backend.app.core.logging.logging_config import setup_logging
from backend.app.core.middleware.access_log import register_access_log_middleware
from backend.app.core.middleware.request_context import register_request_context_middleware
from backend.app.router_registry import register_routers

setup_logging()
logger = logging.getLogger("backend.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("西游问典 RAG API 启动")
    yield
    logger.info("西游问典 RAG API 关闭")


app = FastAPI(title="西游问典 RAG API", version="0.1.0", lifespan=lifespan)
register_access_log_middleware(app)
register_request_context_middleware(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)
register_routers(app)
