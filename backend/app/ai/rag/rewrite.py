from __future__ import annotations

import re
from typing import Any

from backend.app.config import LLM_MODEL_DEFAULT
from backend.app.ai.rag.llm_client import llm_client
from backend.app.utils.pricing import Usage, cost_llm_for_model
from backend.app.utils.text import normalize_query_terms

ALIASES = [
    ("悟空", "孙悟空"),
    ("猴王", "美猴王"),
    ("八戒", "猪八戒"),
    ("悟净", "沙悟净"),
    ("沙僧", "沙悟净"),
    ("师父", "唐僧"),
    ("三藏", "唐僧"),
]
PRONOUN_HINTS = ["他", "她", "它", "这人", "这位", "那个", "这人是谁", "后来叫什么"]


def _history_entities(messages: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for msg in reversed(messages[-6:]):
        content = str(msg.get("content") or msg.get("text") or "")
        for term in normalize_query_terms(content):
            if term not in terms:
                terms.append(term)
    return terms[:6]


def _needs_llm_rewrite(question: str, history_keywords: list[str]) -> bool:
    if not any(h in question for h in PRONOUN_HINTS):
        return False
    return not history_keywords


def rewrite_query(question: str, messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    original = str(question or "").strip()
    text = original
    notes: list[str] = []
    stripped = re.sub(r"^(请问|问一下|我想知道|帮我看看|告诉我)", "", text).strip()
    if stripped and stripped != text:
        text = stripped
        notes.append("去掉口语前缀")
    text = re.sub(r"[吗呢啊呀？?]+$", "", text).strip() or text
    if text != original:
        notes.append("去掉句末语气词")
    for short, full in ALIASES:
        if short in text:
            text = text.replace(short, full)
            notes.append(f"简称补为{full}")
    history_terms = _history_entities(messages or [])
    history_keywords: list[str] = []
    if any(h in original for h in PRONOUN_HINTS) and history_terms:
        for term in history_terms:
            if term not in text:
                history_keywords.append(term)
        if history_keywords:
            text = f"{text} {' '.join(history_keywords[:4])}".strip()
            notes.append("结合近期上下文补充原著关键词")
    keyword_terms = normalize_query_terms(text)
    llm_model = LLM_MODEL_DEFAULT
    llm_usage: Usage | None = None
    llm_cost = None
    method = "规则改写 + 上下文增强"
    if _needs_llm_rewrite(original, history_keywords):
        try:
            llm_text, llm_usage = llm_client.rewrite_question(original, messages, model=llm_model)
            cleaned = str(llm_text or "").strip().splitlines()[0].strip()
            if cleaned and cleaned != original:
                text = cleaned
                method = "规则改写 + LLM 指代消解"
                notes.append(f"LLM({llm_model}) 结合上下文改写指代问句")
                keyword_terms = normalize_query_terms(text)
        except Exception as exc:  # pragma: no cover - network/provider errors
            notes.append(f"LLM 指代改写失败：{exc}")
    if llm_usage:
        llm_cost = cost_llm_for_model(
            llm_usage.input_tokens or 0,
            llm_usage.output_tokens or 0,
            model=llm_model,
            in_known=bool(llm_usage.known),
            out_known=bool(llm_usage.known),
        ).as_dict()
    return {
        "original": original,
        "rewritten": text or original,
        "reason": "；".join(notes) if notes else "问句已经具体，保留原意",
        "method": method,
        "llm_model": llm_model if llm_usage else None,
        "llm_usage": None if not llm_usage else {
            "input_tokens": llm_usage.input_tokens,
            "output_tokens": llm_usage.output_tokens,
            "total_tokens": llm_usage.total_tokens,
            "known": llm_usage.known,
        },
        "llm_cost": llm_cost,
        "keywords": keyword_terms,
        "history_keywords": history_keywords,
    }
