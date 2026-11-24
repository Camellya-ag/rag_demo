from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.config import PRICING, resolve_llm_pricing
from backend.app.utils.text import estimate_tokens


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    known: bool = False

    def merge(self, other: "Usage") -> None:
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            val = getattr(other, key)
            if val is None:
                continue
            cur = getattr(self, key)
            setattr(self, key, (cur or 0) + val)
        self.known = self.known or other.known


@dataclass
class Cost:
    amount: float | None = 0.0
    currency: str = "CNY"
    usage: Usage = field(default_factory=Usage)
    usage_known: bool = False
    note: str = ""

    def as_dict(self) -> dict:
        amount = self.amount
        if not self.usage_known:
            amount = None
        elif amount is not None:
            amount = round(amount, 6)
        return {
            "amount": amount,
            "currency": self.currency,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "total_tokens": self.usage.total_tokens,
            },
            "usage_known": self.usage_known,
            "note": self.note,
        }


def yuan_by_tokens(tokens: int, per_1k: float) -> float:
    if tokens <= 0 or per_1k <= 0:
        return 0.0
    return round((tokens / 1000.0) * per_1k, 6)


def cost_embed(text_or_tokens: str | int, usage: Usage | None = None) -> Cost:
    tokens = text_or_tokens if isinstance(text_or_tokens, int) else estimate_tokens(text_or_tokens)
    is_token_budget = isinstance(text_or_tokens, int)
    usage = usage or Usage(input_tokens=tokens, total_tokens=tokens, known=not is_token_budget)
    known = bool(usage.known)
    if known and tokens:
        amount = yuan_by_tokens(tokens, PRICING["embedding_per_1k"])
        note = ""
    elif is_token_budget and tokens:
        amount = yuan_by_tokens(tokens, PRICING["embedding_per_1k"])
        note = f"按文本长度估算 token；参考单价 {PRICING['embedding_per_1k']} 元/千 token（非实测 usage）"
    else:
        amount = None
        note = "按文本长度估算"
    return Cost(amount=amount, usage=usage, usage_known=known, note=note)


def cost_unknown(note: str = "用量未知，费用无法可靠估算") -> Cost:
    return Cost(amount=None, usage_known=False, note=note)


def cost_rerank(tokens: int, usage: Usage | None = None) -> Cost:
    usage = usage or Usage(input_tokens=tokens, total_tokens=tokens, known=False)
    amount = yuan_by_tokens(tokens, PRICING["rerank_per_1k"]) if usage.known and tokens else None
    return Cost(
        amount=amount,
        usage=usage,
        usage_known=usage.known,
        note="" if usage.known else "按候选拼接长度估算",
    )


def cost_llm(input_tokens: int, output_tokens: int, in_known=False, out_known=False) -> Cost:
    model_name, in_rate, out_rate = resolve_llm_pricing(None)
    known = bool(in_known and out_known and in_rate is not None and out_rate is not None)
    usage = Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        known=known,
    )
    if not known:
        return Cost(amount=None, usage=usage, usage_known=False, note=f"{model_name} token 用量未知")
    amount = yuan_by_tokens(input_tokens, in_rate or 0.0) + yuan_by_tokens(output_tokens, out_rate or 0.0)
    return Cost(amount=amount, usage=usage, usage_known=True, note="")


def cost_llm_for_model(
    input_tokens: int,
    output_tokens: int,
    *,
    model: str | None,
    in_known=False,
    out_known=False,
) -> Cost:
    model_name, in_rate, out_rate = resolve_llm_pricing(model)
    known = bool(in_known and out_known and in_rate is not None and out_rate is not None)
    usage = Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        known=known,
    )
    if not known:
        note = f"{model_name} 单价未配置或 token 未知"
        if in_rate is None or out_rate is None:
            note = f"{model_name} 单价未配置"
        return Cost(amount=None, usage=usage, usage_known=False, note=note)
    amount = yuan_by_tokens(input_tokens, in_rate) + yuan_by_tokens(output_tokens, out_rate)
    return Cost(amount=amount, usage=usage, usage_known=True, note="")
