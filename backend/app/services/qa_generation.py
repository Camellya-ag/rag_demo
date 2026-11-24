from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from backend.app.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    QA_PAIRS_JSONL,
    QA_QUESTIONS_PER_CHAPTER,
    SOURCE_FILE,
)
from backend.app.services.source_loader import SourceLoader, source_loader
from backend.app.utils.pricing import Cost, Usage, cost_unknown, yuan_by_tokens
from backend.app.utils.text import estimate_tokens, snippet

DEFAULT_QA_GEN_MODEL = os.getenv("XIYOU_QA_GEN_MODEL", "qwen-flash")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_CHAPTER_CHARS_FOR_LLM = int(os.getenv("XIYOU_QA_GEN_MAX_CHARS", "12000"))
MAX_QUESTIONS_PER_UNIT = int(os.getenv("XIYOU_QA_GEN_MAX_QUESTIONS", "4"))
MAX_CHAPTERS_PER_RUN = int(os.getenv("XIYOU_QA_GEN_MAX_CHAPTERS", "100"))
MAX_CHUNKS_PER_RUN = int(os.getenv("XIYOU_QA_GEN_MAX_CHUNKS", "256"))
RECALL_ONLY_HINT = "白话问答仅作召回线索；证据必须引用 evidence 对应原文片段，不能使用 answer_summary 作答。"

_PUNCT_RE = re.compile(r"[\s，。；、：！？,.!?;:'\"()（）【】《》\[\]\-―—·]+")


def normalize_model_name(model: str | None) -> str:
    model = (model or DEFAULT_QA_GEN_MODEL).strip()
    return model or DEFAULT_QA_GEN_MODEL


def resolve_model_pricing(model: str | None) -> tuple[str, float, float]:
    """问答生成单价与模型绑定：优先 QA 专用环境变量，否则回退全局 LLM 单价（config）。"""
    from backend.app.config import resolve_llm_pricing

    model_name = normalize_model_name(model)
    slug = re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_")
    in_key = f"PRICE_QA_GEN_{slug.upper()}_IN_PER_1K"
    out_key = f"PRICE_QA_GEN_{slug.upper()}_OUT_PER_1K"
    input_rate = os.getenv(in_key) or os.getenv("XIYOU_QA_GEN_PRICE_IN_PER_1K")
    output_rate = os.getenv(out_key) or os.getenv("XIYOU_QA_GEN_PRICE_OUT_PER_1K")
    if input_rate is not None and output_rate is not None:
        return model_name, float(input_rate), float(output_rate)
    _, in_fallback, out_fallback = resolve_llm_pricing(model_name)
    if in_fallback is None or out_fallback is None:
        raise QaGenerationError(
            f"missing_model_pricing:{model_name}; configure {in_key}/{out_key} "
            "or XIYOU_QA_GEN_PRICE_IN_PER_1K/XIYOU_QA_GEN_PRICE_OUT_PER_1K"
        )
    return model_name, float(in_fallback), float(out_fallback)


def cost_qa_generation(
    input_tokens: int,
    output_tokens: int,
    *,
    model: str,
    in_known: bool,
    out_known: bool,
) -> Cost:
    model_name, in_rate, out_rate = resolve_model_pricing(model)
    usage = Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        known=in_known and out_known,
    )
    amount = yuan_by_tokens(input_tokens, in_rate) + yuan_by_tokens(output_tokens, out_rate)
    note = (
        f"模型 {model_name} 按输入/输出分开计价："
        f"IN {in_rate}/1K tokens, OUT {out_rate}/1K tokens"
    )
    if not usage.known:
        note += "（当前为 token 估算，非百炼实测 usage）"
    return Cost(amount=amount, usage=usage, usage_known=usage.known, note=note)


class QaGenerationError(RuntimeError):
    """问答生成基础异常。"""


class QaGenerationNotConfirmed(QaGenerationError):
    """未显式确认，禁止发起付费调用。"""


class QaGenerationMissingApiKey(QaGenerationError):
    """缺少百炼 API Key。"""


class QaGenerationCancelled(QaGenerationError):
    """生成任务被取消。"""


class GenerationScopeKind(str, Enum):
    CHAPTERS = "chapters"
    CHUNKS = "chunks"
    FULL_BOOK = "full_book"


@dataclass
class EvidenceAnchor:
    quote: str
    start_line: int
    end_line: int
    start_char: int
    end_char: int


@dataclass
class QaGenerationRecord:
    id: str
    chapter: int
    chapter_title: str
    question: str
    answer_summary: str
    evidence: EvidenceAnchor
    mapped_chunk_ids: list[str] = field(default_factory=list)
    source_file: str = "西游记.txt"
    verified: bool = False
    verification_note: str = ""
    origin_chunk_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chapter": self.chapter,
            "chapter_title": self.chapter_title,
            "question": self.question,
            "answer_summary": self.answer_summary,
            "evidence": {
                "quote": self.evidence.quote,
                "start_line": self.evidence.start_line,
                "end_line": self.evidence.end_line,
                "start_char": self.evidence.start_char,
                "end_char": self.evidence.end_char,
            },
            "mapped_chunk_ids": list(self.mapped_chunk_ids),
            "source_file": self.source_file,
            "verified": self.verified,
            "verification_note": self.verification_note,
            "origin_chunk_id": self.origin_chunk_id,
            "meta": {
                "recall_only": True,
                "answer_is_evidence": False,
                "non_evidence_hint": RECALL_ONLY_HINT,
            },
        }


@dataclass
class GenerationScope:
    kind: GenerationScopeKind = GenerationScopeKind.CHAPTERS
    chapter_ids: list[int] | None = None
    chunk_ids: list[int] | None = None
    questions_per_chapter: int = QA_QUESTIONS_PER_CHAPTER
    questions_per_chunk: int = 1
    chapter_limit: int | None = None
    chunk_limit: int | None = None

    def normalized(self) -> "GenerationScope":
        qpc = max(1, min(self.questions_per_chapter, MAX_QUESTIONS_PER_UNIT))
        qpk = max(1, min(self.questions_per_chunk, MAX_QUESTIONS_PER_UNIT))
        return GenerationScope(
            kind=self.kind,
            chapter_ids=list(self.chapter_ids or []),
            chunk_ids=list(self.chunk_ids or []),
            questions_per_chapter=qpc,
            questions_per_chunk=qpk,
            chapter_limit=self.chapter_limit,
            chunk_limit=self.chunk_limit,
        )


@dataclass
class GenerationUnit:
    unit_id: str
    kind: str
    chapter: int
    chapter_title: str
    text: str
    origin_chunk_id: str | None = None


@dataclass
class GenerationEstimate:
    scope: GenerationScope
    units: int
    expected_questions: int
    calls: int
    cost: Cost
    model: str
    requires_confirmation: bool = True
    message: str = "预估完成；确认后才可调用百炼生成问答候选"

    def as_dict(self) -> dict[str, Any]:
        pricing = {}
        try:
            _, in_rate, out_rate = resolve_model_pricing(self.model)
            pricing = {
                "model": self.model,
                "input_per_1k": in_rate,
                "output_per_1k": out_rate,
            }
        except QaGenerationError:
            pricing = {"model": self.model, "configured": False}
        return {
            "scope": {
                "kind": self.scope.kind.value,
                "chapter_ids": self.scope.chapter_ids,
                "chunk_ids": self.scope.chunk_ids,
                "questions_per_chapter": self.scope.questions_per_chapter,
                "questions_per_chunk": self.scope.questions_per_chunk,
            },
            "units": self.units,
            "expected_questions": self.expected_questions,
            "calls": self.calls,
            "model": self.model,
            "requires_confirmation": self.requires_confirmation,
            "message": self.message,
            "pricing": pricing,
            "cost": self.cost.as_dict(),
        }


@dataclass
class GenerationFailure:
    unit_id: str
    error: str


@dataclass
class GenerationResult:
    status: str
    records: list[QaGenerationRecord]
    verified_count: int
    rejected_count: int
    cost: Cost
    failures: list[GenerationFailure] = field(default_factory=list)
    cancelled: bool = False
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "generated_count": len(self.records),
            "verified_count": self.verified_count,
            "rejected_count": self.rejected_count,
            "cancelled": self.cancelled,
            "message": self.message,
            "cost": self.cost.as_dict(),
            "failures": [{"unit_id": f.unit_id, "error": f.error} for f in self.failures],
            "records": [row.to_dict() for row in self.records],
        }


class QaLlmClient(Protocol):
    def generate_rows(
        self,
        *,
        unit: GenerationUnit,
        max_questions: int,
    ) -> tuple[list[dict[str, Any]], Usage]: ...


def resolve_api_key() -> str | None:
    key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
    if not key or key.startswith("your_"):
        return None
    return key


def normalize_for_match(text: str) -> str:
    return _PUNCT_RE.sub("", text)


def line_of_char(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def find_quote_span(text: str, quote: str) -> tuple[int, int] | None:
    if not quote:
        return None
    pos = text.find(quote)
    if pos >= 0:
        return pos, pos + len(quote)

    compact_text = normalize_for_match(text)
    compact_quote = normalize_for_match(quote)
    if not compact_quote:
        return None
    pos = compact_text.find(compact_quote)
    if pos < 0:
        return None

    start = None
    end = None
    compact_cursor = 0
    last_idx = 0
    for idx, ch in enumerate(text):
        if _PUNCT_RE.fullmatch(ch) or ch.isspace():
            continue
        if compact_cursor == pos and start is None:
            start = idx
        if compact_cursor == pos + len(compact_quote) - 1:
            end = idx + 1
            break
        compact_cursor += 1
        last_idx = idx
    if start is None:
        return None
    if end is None:
        end = min(len(text), last_idx + 1)
    return start, end


def build_evidence_anchor(text: str, quote: str) -> EvidenceAnchor | None:
    span = find_quote_span(text, quote)
    if not span:
        return None
    start, end = span
    return EvidenceAnchor(
        quote=text[start:end],
        start_line=line_of_char(text, start),
        end_line=line_of_char(text, max(start, end - 1)),
        start_char=start,
        end_char=end,
    )


def verify_record(source_text: str, record: QaGenerationRecord) -> QaGenerationRecord:
    anchor = build_evidence_anchor(source_text, record.evidence.quote)
    if anchor is None:
        record.verified = False
        record.verification_note = "evidence_quote_not_found_in_source"
        return record
    record.evidence = anchor
    record.verified = True
    record.verification_note = "anchored_to_source"
    return record


def map_record_to_chunks(record: QaGenerationRecord, loader: SourceLoader) -> QaGenerationRecord:
    record.mapped_chunk_ids = loader.find_chunk_ids_for_range(
        record.evidence.start_char,
        record.evidence.end_char,
        chunk_size=CHUNK_SIZE,
        overlap=CHUNK_OVERLAP,
    )
    return record


class BailianFlashClient:
    """百炼 OpenAI 兼容接口，默认使用低成本 flash/turbo 模型。"""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or DEFAULT_QA_GEN_MODEL
        self.model = normalize_model_name(self.model)
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        api_key = resolve_api_key()
        if not api_key:
            raise QaGenerationMissingApiKey("missing_api_key")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise QaGenerationError("openai_not_installed") from exc
        self._client = OpenAI(api_key=api_key, base_url=DASHSCOPE_BASE_URL)
        return self._client

    @staticmethod
    def _parse_json(text: str) -> Any:
        text = (text or "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\[.*\]|\{.*\}", text, re.S)
            if not match:
                raise
            return json.loads(match.group(0))

    def generate_rows(self, *, unit: GenerationUnit, max_questions: int) -> tuple[list[dict[str, Any]], Usage]:
        client = self._ensure_client()
        prompt = (
            f"你是《西游记》章节问答标注员。请仅依据下面原文，生成{max_questions}条白话问答候选。\n"
            "硬性规则：\n"
            "1) question 用现代白话；\n"
            "2) answer_summary 仅作检索线索，禁止编造；\n"
            "3) evidence_quote 必须是原文逐字摘录；\n"
            "4) 只输出 JSON 数组，字段 question/answer_summary/evidence_quote。\n\n"
            f"【{unit.chapter_title or f'第{unit.chapter}回'} · {unit.unit_id}】\n"
            f"{unit.text[:MAX_CHAPTER_CHARS_FOR_LLM]}"
        )
        response = client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "你只返回合法 JSON。"},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "[]"
        payload = self._parse_json(content)
        if isinstance(payload, dict):
            rows = payload.get("items", [])
        elif isinstance(payload, list):
            rows = payload
        else:
            raise QaGenerationError("invalid_generation_payload")

        usage = getattr(response, "usage", None)
        stats = Usage()
        if usage is not None:
            stats.input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            stats.output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            stats.total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
            stats.known = True
        else:
            stats.input_tokens = estimate_tokens(prompt)
            stats.output_tokens = estimate_tokens(content)
            stats.total_tokens = (stats.input_tokens or 0) + (stats.output_tokens or 0)
            stats.known = False
        return rows[:max_questions], stats


class QaGenerationService:
    """主后端正式问答对生成模块（独立于 qa_pilot）。"""

    def __init__(
        self,
        loader: SourceLoader | None = None,
        model: str | None = None,
        llm_client: QaLlmClient | None = None,
        output_path=QA_PAIRS_JSONL,
    ) -> None:
        self.loader = loader or source_loader
        self.model = normalize_model_name(model or DEFAULT_QA_GEN_MODEL)
        self.output_path = output_path
        self._llm_client = llm_client
        self._cancel_event = threading.Event()
        self._active = False

    def cancel(self) -> None:
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        self._cancel_event.clear()

    def _source_text(self) -> str:
        return self.loader.read_text()

    def _chapter_units(self, scope: GenerationScope) -> list[GenerationUnit]:
        text = self._source_text()
        chapter_rows = self.loader.split_chapters(text)
        if scope.kind == GenerationScopeKind.FULL_BOOK:
            selected = chapter_rows[:MAX_CHAPTERS_PER_RUN]
        else:
            wanted = set(scope.chapter_ids or [])
            selected = [row for row in chapter_rows if row[0] in wanted] if wanted else chapter_rows
            if scope.chapter_limit:
                selected = selected[: scope.chapter_limit]
            selected = selected[:MAX_CHAPTERS_PER_RUN]
        units: list[GenerationUnit] = []
        for chapter, title, body in selected:
            units.append(
                GenerationUnit(
                    unit_id=f"ch-{chapter:03d}",
                    kind="chapter",
                    chapter=chapter,
                    chapter_title=title,
                    text=body,
                )
            )
        return units

    def _chunk_units(self, scope: GenerationScope) -> list[GenerationUnit]:
        chunks = self.loader.chunk(chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        if scope.chunk_ids:
            wanted = {str(x) for x in scope.chunk_ids}
            expanded = set(wanted)
            for item in wanted:
                if item.isdigit():
                    expanded.add(f"c-{int(item):06d}")
            chunks = [c for c in chunks if c.id in expanded or str(c.chapter) in wanted]
        if scope.chapter_ids:
            wanted = set(scope.chapter_ids)
            chunks = [c for c in chunks if c.chapter in wanted]
        if scope.chunk_limit:
            chunks = chunks[: scope.chunk_limit]
        chunks = chunks[:MAX_CHUNKS_PER_RUN]
        return [
            GenerationUnit(
                unit_id=chunk.id,
                kind="chunk",
                chapter=chunk.chapter,
                chapter_title=chunk.chapter_title,
                text=chunk.text,
                origin_chunk_id=chunk.id,
            )
            for chunk in chunks
        ]

    def resolve_units(self, scope: GenerationScope | None = None) -> tuple[GenerationScope, list[GenerationUnit]]:
        scope = (scope or GenerationScope()).normalized()
        if scope.kind == GenerationScopeKind.CHUNKS:
            units = self._chunk_units(scope)
        else:
            units = self._chapter_units(scope)
        return scope, units

    def status(self) -> dict[str, Any]:
        meta = self.loader.meta()
        pricing_status = {"configured": False}
        try:
            model_name, in_rate, out_rate = resolve_model_pricing(self.model)
            pricing_status = {
                "configured": True,
                "model": model_name,
                "input_per_1k": in_rate,
                "output_per_1k": out_rate,
            }
        except QaGenerationError as exc:
            pricing_status["error"] = str(exc)
        return {
            "source_file": str(SOURCE_FILE),
            "output_path": str(self.output_path),
            "model": self.model,
            "pricing": pricing_status,
            "chapters_total": meta.chapters,
            "active": self._active,
            "cancelled": self._cancel_event.is_set(),
            "policy": {
                "requires_confirmation": True,
                "answer_is_evidence": False,
                "mapped_to_chunks": True,
            },
        }

    def estimate(self, scope: GenerationScope | None = None) -> GenerationEstimate:
        scope, units = self.resolve_units(scope)
        if not units:
            return GenerationEstimate(
                scope=scope,
                units=0,
                expected_questions=0,
                calls=0,
                cost=cost_unknown("无可生成单元"),
                model=self.model,
                message="未找到可生成的章节或切片",
            )

        input_tokens = 0
        output_tokens = 0
        questions = 0
        for unit in units:
            qn = scope.questions_per_chunk if unit.kind == "chunk" else scope.questions_per_chapter
            questions += qn
            input_tokens += estimate_tokens(unit.text[:MAX_CHAPTER_CHARS_FOR_LLM]) + 450
            output_tokens += estimate_tokens(json.dumps({"items": [{"question": "x", "answer_summary": "y", "evidence_quote": "z"}]}, ensure_ascii=False)) * qn
        cost = cost_qa_generation(input_tokens, output_tokens, model=self.model, in_known=False, out_known=False)
        cost.note = f"估算 {len(units)} 次调用，预期 {questions} 条问答候选；{cost.note}"
        return GenerationEstimate(
            scope=scope,
            units=len(units),
            expected_questions=questions,
            calls=len(units),
            cost=cost,
            model=self.model,
        )

    def _client(self) -> QaLlmClient:
        if self._llm_client is not None:
            return self._llm_client
        if self._llm_client is None:
            self._llm_client = BailianFlashClient(model=self.model)
        return self._llm_client

    def generate(
        self,
        *,
        scope: GenerationScope | None = None,
        confirm: bool = False,
        cancel_event: threading.Event | None = None,
        run_id: str | None = None,
    ) -> GenerationResult:
        if not confirm:
            raise QaGenerationNotConfirmed("generation_requires_confirmation")

        scope, units = self.resolve_units(scope)
        if not units:
            return GenerationResult(
                status="failed",
                records=[],
                verified_count=0,
                rejected_count=0,
                cost=cost_unknown("无可生成单元"),
                message="未找到可生成的章节或切片",
            )

        cancel_token = cancel_event or self._cancel_event
        if cancel_event is None:
            self._cancel_event.clear()
        self._active = True
        source_text = self._source_text()
        client = self._client()

        usage = Usage()
        records: list[QaGenerationRecord] = []
        failures: list[GenerationFailure] = []
        rejected = 0
        cancelled = False
        prefix = run_id or uuid.uuid4().hex[:8]

        try:
            for unit in units:
                if cancel_token.is_set():
                    cancelled = True
                    break
                max_questions = scope.questions_per_chunk if unit.kind == "chunk" else scope.questions_per_chapter
                try:
                    rows, call_usage = client.generate_rows(unit=unit, max_questions=max_questions)
                    usage.merge(call_usage)
                except Exception as exc:
                    failures.append(GenerationFailure(unit_id=unit.unit_id, error=str(exc)))
                    continue

                for idx, row in enumerate(rows, start=1):
                    quote = str(row.get("evidence_quote", "")).strip()
                    if not quote:
                        rejected += 1
                        continue
                    rec = QaGenerationRecord(
                        id=f"{prefix}-{unit.unit_id}-{idx:02d}",
                        chapter=unit.chapter,
                        chapter_title=unit.chapter_title,
                        question=str(row.get("question", "")).strip(),
                        answer_summary=snippet(str(row.get("answer_summary", "")).strip(), 120),
                        evidence=EvidenceAnchor(quote=quote, start_line=0, end_line=0, start_char=0, end_char=0),
                        origin_chunk_id=unit.origin_chunk_id,
                    )
                    rec = verify_record(source_text, rec)
                    if not rec.verified:
                        rejected += 1
                        continue
                    rec = map_record_to_chunks(rec, self.loader)
                    if not rec.mapped_chunk_ids:
                        rec.verified = False
                        rec.verification_note = "chunk_mapping_failed"
                        rejected += 1
                        continue
                    records.append(rec)
        finally:
            self._active = False

        known_in = bool(usage.known and usage.input_tokens is not None)
        known_out = bool(usage.known and usage.output_tokens is not None)
        cost = cost_qa_generation(
            usage.input_tokens or 0,
            usage.output_tokens or 0,
            model=self.model,
            in_known=known_in,
            out_known=known_out,
        )
        if failures and not usage.known:
            cost.note = f"部分调用失败或 usage 未知；{cost.note}"
        elif failures:
            cost.note = f"部分单元失败，已对成功调用按实测 usage 计价；{cost.note}"
        elif usage.known:
            cost.note = f"按百炼返回 usage 输入/输出分开计价；{cost.note}"
        else:
            cost.note = f"未返回 usage，按输入/输出 token 估算；{cost.note}"

        if cancelled:
            status = "cancelled"
            message = "生成已取消，已保留已完成批次结果"
        elif failures and records:
            status = "partial"
            message = f"部分成功：{len(records)} 条已验证，{len(failures)} 个单元失败"
        elif failures and not records:
            status = "failed"
            message = "全部单元失败，未产出可验证问答"
        else:
            status = "succeeded"
            message = f"生成完成，产出 {len(records)} 条可验证问答候选"

        return GenerationResult(
            status=status,
            records=records,
            verified_count=len(records),
            rejected_count=rejected,
            cost=cost,
            failures=failures,
            cancelled=cancelled,
            message=message,
        )

    def persist(self, records: list[QaGenerationRecord], *, append: bool = True) -> int:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, dict[str, Any]] = {}
        if append and self.output_path.exists():
            for line in self.output_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                existing[str(row.get("id"))] = row
        for row in records:
            existing[row.id] = row.to_dict()
        with self.output_path.open("w", encoding="utf-8") as fh:
            for row in existing.values():
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(records)


qa_generation_service = QaGenerationService()

