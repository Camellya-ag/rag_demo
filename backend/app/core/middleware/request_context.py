from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        return await call_next(request)


def register_request_context_middleware(app: FastAPI) -> None:
    app.add_middleware(RequestContextMiddleware)
