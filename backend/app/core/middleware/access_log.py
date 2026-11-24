from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

http_logger = logging.getLogger("backend.app.http")
_SKIP_PREFIXES = ("/docs", "/redoc", "/openapi.json")


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(_SKIP_PREFIXES):
            return await call_next(request)
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        rid = getattr(request.state, "request_id", "-")
        http_logger.info("%s %s %s %sms", request.method, path, response.status_code, elapsed_ms, extra={"request_id": rid})
        return response


def register_access_log_middleware(app: FastAPI) -> None:
    app.add_middleware(AccessLogMiddleware)
