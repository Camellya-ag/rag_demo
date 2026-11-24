from __future__ import annotations

import os
from typing import Iterable

from openai import OpenAI

from backend.app.config import EMBEDDING_DIM, EMBEDDING_MODEL
from backend.app.utils.pricing import Usage


class EmbeddingClient:
    def __init__(self) -> None:
        self._client: OpenAI | None = None
        self.model = EMBEDDING_MODEL

    def _get_client(self) -> OpenAI:
        if self._client is None:
            api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
            if not api_key:
                raise RuntimeError("未配置 DASHSCOPE_API_KEY / ALIYUN_API_KEY")
            self._client = OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        return self._client

    def embed(self, texts: Iterable[str], *, batch_size: int = 10) -> tuple[list[list[float]], Usage]:
        items = [str(t) for t in texts]
        if not items:
            return [], Usage()
        batch_size = max(1, min(int(batch_size), 10))
        client = self._get_client()
        vectors: list[list[float]] = []
        merged = Usage()
        for start in range(0, len(items), batch_size):
            chunk = items[start : start + batch_size]
            response = client.embeddings.create(
                model=self.model,
                input=chunk,
                encoding_format="float",
                dimensions=EMBEDDING_DIM,
            )
            vectors.extend(row.embedding for row in response.data)
            usage = getattr(response, "usage", None)
            if usage and getattr(usage, "total_tokens", None):
                merged.merge(
                    Usage(input_tokens=int(usage.total_tokens), total_tokens=int(usage.total_tokens), known=True)
                )
            else:
                estimated = sum(max(1, int(len(t) * 0.7)) for t in chunk)
                merged.merge(Usage(input_tokens=estimated, total_tokens=estimated, known=False))
        if merged.total_tokens and merged.known:
            merged.input_tokens = merged.total_tokens
        return vectors, merged


embedding_client = EmbeddingClient()
