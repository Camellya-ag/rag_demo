from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

BLOCKED_HTTP_PREFIXES = (
    "dashscope.aliyuncs.com",
    "openai.com",
)


def _host_of(url: Any) -> str:
    return str(getattr(url, "full_url", url) or "")


def _blocked_host(host: str) -> bool:
    hostname = (urlsplit(host).hostname or "").lower()
    return (
        hostname == "openai.com"
        or hostname.endswith(".openai.com")
        or (hostname.startswith("dashscope") and hostname.endswith(".aliyuncs.com"))
    )


@dataclass
class OfflineProviderGuard:
    installed: bool = False
    httpx_client_send: Any = None
    httpx_client_request: Any = None
    urllib_urlopen: Any = None


_GUARD = OfflineProviderGuard()


def install_offline_llm_guard() -> None:
    if _GUARD.installed:
        return
    # The installed OpenAI SDK uses httpx2; other clients still use httpx.
    for name in ("httpx", "httpx2"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        original_send = module.Client.send

        def guarded_send(self, request, *args, _send=original_send, **kwargs):
            host = _host_of(getattr(request, "url", ""))
            if _blocked_host(host):
                raise RuntimeError(f"offline guard blocks external HTTP request to provider host: {urlsplit(host).hostname}")
            return _send(self, request, *args, **kwargs)

        module.Client.send = guarded_send

    try:
        import requests
    except ImportError:
        requests = None
    if requests is not None:
        original_requests_send = requests.Session.send

        def guarded_requests_send(self, request, *args, **kwargs):
            host = _host_of(request.url)
            if _blocked_host(host):
                raise RuntimeError(f"offline guard blocks external HTTP request to provider host: {urlsplit(host).hostname}")
            return original_requests_send(self, request, *args, **kwargs)

        requests.Session.send = guarded_requests_send

    import urllib.request as urllib_request
    original_urlopen = urllib_request.urlopen

    def guarded_urlopen(url, *args, **kwargs):
        host = _host_of(url)
        if _blocked_host(host):
            raise RuntimeError(f"offline guard blocks external HTTP request to provider host: {urlsplit(host).hostname}")
        return original_urlopen(url, *args, **kwargs)

    urllib_request.urlopen = guarded_urlopen
    _GUARD.installed = True
