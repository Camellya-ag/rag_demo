from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.api.contract_catalog import CHAT_SSE_EVENTS, CONTRACT_ROUTES, DEPRECATED_ROUTE_HINTS
from backend.app.main import app


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_catalog_not_empty(self) -> None:
        self.assertGreaterEqual(len(CONTRACT_ROUTES), 8)
        self.assertIn("stage", CHAT_SSE_EVENTS)
        self.assertIn("/chat/stream", DEPRECATED_ROUTE_HINTS)

    def test_routes_registered(self) -> None:
        openapi_paths = set((app.openapi().get("paths") or {}).keys())
        for _method, path, _desc in CONTRACT_ROUTES:
            full = f"/api{path}"
            self.assertIn(full, openapi_paths, msg=f"OpenAPI 缺少 {full}")

    def test_health_schema(self) -> None:
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("ok", "status", "active_collection", "qa_pairs"):
            self.assertIn(key, body)

    def test_knowledge_source_qa_count_consistency(self) -> None:
        resp = self.client.get("/api/knowledge/source")
        self.assertEqual(resp.status_code, 200)
        source = resp.json().get("source") or {}
        qa_pairs = source.get("qa_pairs") or {}
        qa_count = int(source.get("qa_pair_count") or 0)
        verified = int(qa_pairs.get("verified") or 0)
        if verified > 0:
            self.assertEqual(qa_count, verified)

    def test_estimate_response_shape(self) -> None:
        resp = self.client.post("/api/knowledge/index/estimate", json={"mode": "rebuild"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("mode", "chunk_count", "qa_pair_count", "total_cost", "stages", "requires_confirmation"):
            self.assertIn(key, body)

    @patch("backend.app.api.routes.rag_chat_service.run")
    def test_chat_query_json_events(self, run_mock) -> None:
        run_mock.return_value = {
            "text": "答案[1]",
            "hits": [],
            "meta": {"trace_id": "trace_contract", "latency": 1, "tokens": 2},
            "trace": {"trace_id": "trace_contract", "stages": {}},
        }
        resp = self.client.post(
            "/api/chat/query",
            headers={"Accept": "application/json"},
            json={"question": "孙悟空是怎么出生的？", "settings": {"streaming": False, "top_k": 3}},
        )
        self.assertEqual(resp.status_code, 200)
        events = resp.json().get("events") or []
        types = {e.get("type") for e in events}
        self.assertIn("answer", types)
        self.assertIn("done", types)


if __name__ == "__main__":
    unittest.main()
