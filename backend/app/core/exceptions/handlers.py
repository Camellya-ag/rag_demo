from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.core.exceptions.errors import BusinessError

logger = logging.getLogger("backend.app.errors")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessError)
    async def business_error_handler(request: Request, exc: BusinessError):
        logger.info("%s %s business error %s: %s", request.method, request.url.path, exc.status_code, exc.message)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("unhandled error %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})
