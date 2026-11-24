from __future__ import annotations

import os
from typing import Iterable

from backend.app.config import RERANK_MODEL
from backend.app.utils.pricing import Usage
from backend.app.utils.text import estimate_tokens


class RerankClient:
    def __init__(self) -> None:
        self.model = RERANK_MODEL

    def score(self, query: str, documents: Iterable[str]) -> tuple[list[float], Usage]:
        docs = [str(d) for d in documents]
        if not docs:
            return [], Usage()
        try:
            from dashscope import TextReRank
        except ImportError as exc:
            raise RuntimeError("需要安装 dashscope") from exc
        api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
        if not api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY / ALIYUN_API_KEY")
        resp = TextReRank.call(
            model=self.model,
            query=query,
            documents=docs,
            top_n=len(docs),
            return_documents=False,
            api_key=api_key,
        )
        if resp.status_code != 200:
            raise RuntimeError(getattr(resp, "message", "rerank failed"))
        scores = [0.0] * len(docs)
        for item in resp.output.results:
            idx = getattr(item, "index", None)
            if idx is not None and 0 <= idx < len(scores):
                scores[idx] = float(item.relevance_score)
        usage = getattr(resp, "usage", None)
        if usage and getattr(usage, "total_tokens", None):
            total = int(usage.total_tokens)
            usage_obj = Usage(input_tokens=total, total_tokens=total, known=True)
        else:
            total = estimate_tokens(query) + sum(estimate_tokens(d) for d in docs)
            usage_obj = Usage(input_tokens=total, total_tokens=total, known=False)
        return scores, usage_obj


rerank_client = RerankClient()
