from __future__ import annotations

import importlib
import unittest

import requests

from backend.tests.offline_provider_guard import install_offline_llm_guard


class ProviderGuardTests(unittest.TestCase):
    def test_httpx_model_requests_never_reach_transport(self) -> None:
        self._check_httpx_family("httpx")

    def test_httpx2_model_requests_never_reach_transport(self) -> None:
        self._check_httpx_family("httpx2")

    def _check_httpx_family(self, name: str) -> None:
        install_offline_llm_guard()
        module = importlib.import_module(name)
        forwarded: list[str] = []

        def receive(request):
            forwarded.append(str(request.url))
            return module.Response(200, json={})

        with module.Client(transport=module.MockTransport(receive)) as client:
            with self.assertRaises(RuntimeError):
                client.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        self.assertEqual(forwarded, [])

    def test_requests_model_requests_never_reach_adapter(self) -> None:
        install_offline_llm_guard()
        forwarded: list[str] = []

        class FakeAdapter(requests.adapters.BaseAdapter):
            def send(self, request, **_kwargs):
                forwarded.append(request.url)
                response = requests.Response()
                response.status_code = 200
                response._content = b"{}"
                return response

            def close(self):
                pass

        with requests.Session() as session:
            session.mount("https://", FakeAdapter())
            with self.assertRaises(RuntimeError):
                session.post("https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank")
        self.assertEqual(forwarded, [])
