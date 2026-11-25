from __future__ import annotations

import re
from typing import Any

from backend.app.config import LLM_MODEL_DEFAULT
from backend.app.ai.rag.llm_client import llm_client
from backend.app.utils.pricing import Usage, cost_llm_for_model
from backend.app.utils.text import normalize_query_terms

ALIASES = [
    ("猴哥", "孙悟空"),
    ("大圣", "孙悟空"),
    ("大师兄", "孙悟空"),
    ("二师兄", "猪八戒"),
    ("三师弟", "沙悟净"),
    ("沙和尚", "沙悟净"),
    ("悟空", "孙悟空"),
    ("猴王", "美猴王"),
    ("八戒", "猪八戒"),
    ("悟净", "沙悟净"),
    ("沙僧", "沙悟净"),
    ("师父", "唐僧"),
    ("三藏", "唐僧"),
]
PRONOUN_HINTS = ["他", "她", "它", "这人", "这位", "那个", "这人是谁", "后来叫什么"]
CANONICAL_NAMES = sorted({full for _, full in ALIASES} | {"美猴王", "唐三藏"}, key=len, reverse=True)
_ALIAS_PATTERN = re.compile(
    "|".join(re.escape(short) for short, _ in sorted(ALIASES, key=lambda x: len(x[0]), reverse=True))
)


def _is_within_canonical_span(text: str, start: int, end: int) -> bool:
    for name in CANONICAL_NAMES:
        idx = text.find(name)
        while idx != -1:
            name_end = idx + len(name)
            if idx <= start and end <= name_end:
                return True
            idx = text.find(name, idx + 1)
    return False


def _apply_aliases(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    alias_map = dict(ALIASES)
    out_parts: list[str] = []
    last = 0
    seen: set[str] = set()
    for match in _ALIAS_PATTERN.finditer(text):
        start, end = match.span()
        short = match.group(0)
        if _is_within_canonical_span(text, start, end):
            continue
        out_parts.append(text[last:start])
        out_parts.append(alias_map[short])
        last = end
        note = f"口语「{short}」规范为「{alias_map[short]}」"
        if note not in seen:
            seen.add(note)
            notes.append(note)
    out_parts.append(text[last:])
    return "".join(out_parts), notes


def _history_entities(messages: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for msg in reversed(messages[-6:]):
        role = str(msg.get("role") or "").lower()
        if role != "user":
            continue
        content = str(msg.get("content") or msg.get("text") or "").strip()
        if not content:
            continue
        content = re.sub(r"^(请问|问一下|我想知道|帮我看看|告诉我)", "", content).strip()
        for name in CANONICAL_NAMES:
            if name in content and name not in terms:
                terms.append(name)
    return terms[:6]


def _needs_llm_rewrite(question: str, history_keywords: list[str]) -> bool:
    if not any(h in question for h in PRONOUN_HINTS):
        return False
    return True


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
    text, alias_notes = _apply_aliases(text)
    notes.extend(alias_notes)
    if "为啥" in text:
        text = text.replace("为啥", "为什么")
        notes.append("口语「为啥」规范为「为什么」")
    history_terms = _history_entities(messages or [])
    history_keywords: list[str] = []
    if any(h in original for h in PRONOUN_HINTS) and len(history_terms) == 1:
        term = history_terms[0]
        if term not in text and term in CANONICAL_NAMES:
            history_keywords = [term]
            text = f"{text} {term}".strip()
            notes.append("结合单实体上下文补充专名")
    elif any(h in original for h in PRONOUN_HINTS) and len(history_terms) > 1:
        notes.append("多实体歧义，保留追问原样等待受控消解")
    ambiguous_reference = any(h in original for h in PRONOUN_HINTS) and len(history_terms) > 1
    keyword_terms = normalize_query_terms(text)
    llm_model = LLM_MODEL_DEFAULT
    llm_usage: Usage | None = None
    llm_cost = None
    method = "规则改写 + 上下文增强"
    if _needs_llm_rewrite(original, history_keywords) and not ambiguous_reference:
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
        "reason": "；".join(notes) if notes else "问句已足够具体，未做语义改写",
        "changed": (text or original) != original,
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
        "ambiguous_reference": ambiguous_reference,
    }
