from __future__ import annotations

import os
from typing import Iterable

from openai import OpenAI

from backend.app.config import LLM_MODEL_DEFAULT
from backend.app.utils.pricing import Usage


class LLMClient:
    def __init__(self) -> None:
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
            if not api_key:
                raise RuntimeError("未配置 DASHSCOPE_API_KEY / ALIYUN_API_KEY")
            self._client = OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        return self._client

    def stream_answer(self, prompt: str, *, model: str | None = None, temperature: float = 0.3):
        model = model or LLM_MODEL_DEFAULT
        stream = self._get_client().chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": "你是《西游记》阅读助手，回答必须基于给定片段，不足则坦诚说明。"},
                {"role": "user", "content": prompt},
            ],
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            usage = getattr(chunk, "usage", None)
            if usage:
                yield {
                    "__usage__": Usage(
                        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                        known=True,
                    )
                }

    def complete(self, prompt: str, *, model: str | None = None, temperature: float = 0.3) -> tuple[str, Usage]:
        model = model or LLM_MODEL_DEFAULT
        response = self._get_client().chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": "你是《西游记》阅读助手。"},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        if usage:
            return text, Usage(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                known=True,
            )
        return text, Usage()

    def rewrite_question(
        self,
        question: str,
        messages: list[dict] | None = None,
        *,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> tuple[str, Usage]:
        model = model or LLM_MODEL_DEFAULT
        history_lines = []
        for msg in (messages or [])[-6:]:
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or msg.get("text") or "").strip()
            if content:
                history_lines.append(f"{role}: {content}")
        history = "\n".join(history_lines) or "（无）"
        prompt = (
            "你是《西游记》检索查询改写器。根据近期对话，将用户追问改写为可独立检索的完整问题。"
            "只输出一行改写结果，不要解释。若无法确定指代，保留原问题。\n"
            f"近期对话：\n{history}\n\n当前问题：{question}\n改写："
        )
        return self.complete(prompt, model=model, temperature=temperature)


llm_client = LLMClient()
