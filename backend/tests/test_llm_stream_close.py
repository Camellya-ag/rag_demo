from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.ai.rag.llm_client import LLMClient


class TrackingStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def __iter__(self):
        for item in self.chunks:
            yield item

    def close(self) -> None:
        self.closed = True


class LlmStreamCloseTests(unittest.TestCase):
    def test_stream_answer_closes_provider_stream(self) -> None:
        client = LLMClient()
        chunk = MagicMock()
        chunk.choices = [MagicMock(delta=MagicMock(content="分"))]
        chunk.usage = None
        tracking = TrackingStream([chunk])
        with patch.object(client, "_chat", return_value=tracking):
            gen = client.stream_answer("prompt")
            self.assertEqual(next(gen), "分")
            gen.close()
        self.assertTrue(tracking.closed)

    def test_stream_answer_closes_on_exception(self) -> None:
        client = LLMClient()

        class RaisingStream:
            def __init__(self) -> None:
                self.closed = False

            def __iter__(self):
                raise RuntimeError("upstream down")
                yield  # pragma: no cover

            def close(self) -> None:
                self.closed = True

        tracking = RaisingStream()
        with patch.object(client, "_chat", return_value=tracking):
            with self.assertRaises(RuntimeError):
                list(client.stream_answer("prompt"))
        self.assertTrue(tracking.closed)

