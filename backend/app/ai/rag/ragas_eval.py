from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.app.ai.rag.evaluation import EvalQuestion
from backend.app.config import EMBEDDING_MODEL, LLM_MODEL_DEFAULT

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

DEFAULT_METRIC_NAMES = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_correctness",
)

_METRIC_IMPORTS: dict[str, str] = {
    "faithfulness": "faithfulness",
    "answer_relevancy": "answer_relevancy",
    "context_precision": "context_precision",
    "context_recall": "context_recall",
    "answer_correctness": "answer_correctness",
}


def contexts_from_hits(hits: list[dict[str, Any]]) -> list[str]:
    contexts: list[str] = []
    for hit in hits or []:
        chunk = hit.get("chunk") if isinstance(hit.get("chunk"), dict) else {}
        text = str(chunk.get("text") or hit.get("text") or "").strip()
        if text:
            contexts.append(text)
    return contexts


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out):
        return None
    return out


def resolve_ragas_models(env: dict[str, str] | None = None) -> tuple[str, str]:
    env = env or {}
    llm = (
        env.get("XIYOU_RAGAS_LLM_MODEL")
        or os.getenv("XIYOU_RAGAS_LLM_MODEL")
        or env.get("XIYOU_EVAL_MODEL")
        or os.getenv("XIYOU_EVAL_MODEL")
        or LLM_MODEL_DEFAULT
    )
    emb = (
        env.get("XIYOU_RAGAS_EMBEDDING_MODEL")
        or os.getenv("XIYOU_RAGAS_EMBEDDING_MODEL")
        or EMBEDDING_MODEL
    )
    return llm, emb


def build_ragas_clients(
    *,
    env: dict[str, str] | None = None,
) -> tuple[Any, Any, str, str]:
    """Return (wrapped_llm, wrapped_embeddings, llm_model, emb_model). Raises on missing deps/key."""
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY / ALIYUN_API_KEY，无法运行 RAGAS")

    llm_model, emb_model = resolve_ragas_models(env)
    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
    except ImportError as exc:
        raise RuntimeError(
            "未安装 RAGAS 评测依赖，请执行: pip install -r backend/requirements-eval.txt"
        ) from exc

    chat = ChatOpenAI(
        model=llm_model,
        api_key=api_key,
        base_url=DASHSCOPE_BASE,
        temperature=0,
    )
    embeddings = OpenAIEmbeddings(
        model=emb_model,
        api_key=api_key,
        base_url=DASHSCOPE_BASE,
        check_embedding_ctx_length=False,
    )
    return LangchainLLMWrapper(chat), LangchainEmbeddingsWrapper(embeddings), llm_model, emb_model


def resolve_metrics(metric_names: list[str] | None = None) -> list[Any]:
    names = list(metric_names or DEFAULT_METRIC_NAMES)
    try:
        from ragas import metrics as ragas_metrics
    except ImportError as exc:
        raise RuntimeError(
            "未安装 RAGAS 评测依赖，请执行: pip install -r backend/requirements-eval.txt"
        ) from exc

    resolved: list[Any] = []
    for name in names:
        key = name.strip().lower()
        attr = _METRIC_IMPORTS.get(key)
        if not attr:
            raise ValueError(f"不支持的 RAGAS 指标: {name}")
        resolved.append(getattr(ragas_metrics, attr))
    return resolved


def build_hf_dataset(
    rows: list[dict[str, Any]],
    questions_by_id: dict[str, EvalQuestion],
) -> tuple[Any, list[int]]:
    """Build HF Dataset and row indices aligned to `rows` (only evaluable cases)."""
    from datasets import Dataset

    questions: list[str] = []
    answers: list[str] = []
    contexts: list[list[str]] = []
    ground_truths: list[str] = []
    row_indices: list[int] = []

    for idx, row in enumerate(rows):
        qid = str(row.get("id") or "")
        item = questions_by_id.get(qid)
        if item is None:
            continue
        if not item.reference_answer:
            continue
        if row.get("error"):
            continue
        prior = row.get("ragas")
        if isinstance(prior, dict) and prior.get("skipped"):
            continue
        questions.append(item.question)
        answers.append(str(row.get("answer_text") or ""))
        contexts.append(contexts_from_hits(row.get("hits") or []))
        ground_truths.append(item.reference_answer)
        row_indices.append(idx)

    if not questions:
        return None, row_indices

    payload = {
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    }
    return Dataset.from_dict(payload), row_indices


def _execute_ragas_subprocess(
    dataset: Any,
    metric_names: list[str],
    *,
    env: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Isolate ragas.evaluate in a child process (avoids Py3.14 asyncio conflicts)."""
    env = env or {}
    # LLM 客户端仅在子进程 worker 内初始化，避免主进程 asyncio 污染
    root = Path(__file__).resolve().parents[3]
    worker = root / "scripts" / "ragas_eval_worker.py"
    if not worker.exists():
        raise RuntimeError(f"缺少 RAGAS worker: {worker}")

    payload = {"metrics": metric_names, "rows": dataset.to_dict()}
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / "in.json"
        out = Path(tmp) / "out.json"
        inp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        proc_env = os.environ.copy()
        proc_env.update({k: str(v) for k, v in env.items() if v})
        completed = subprocess.run(
            [sys.executable, str(worker), str(inp), str(out)],
            env=proc_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(os.getenv("XIYOU_RAGAS_WALL_TIMEOUT", "7200")),
            cwd=str(root.parent),
        )
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip()[-2000:]
            raise RuntimeError(tail or f"ragas worker exit {completed.returncode}")
        data = json.loads(out.read_text(encoding="utf-8"))
    llm_model = str(data.get("ragas_model") or resolve_ragas_models(env)[0])
    emb_model = str(data.get("ragas_embedding_model") or resolve_ragas_models(env)[1])
    return data, llm_model, emb_model


def aggregate_ragas_summary(per_case: list[dict[str, Any]], metric_names: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"evaluated_cases": 0, "skipped_cases": 0}
    for name in metric_names:
        key = name.strip().lower()
        values = [
            _safe_float(c.get("ragas", {}).get(key))
            for c in per_case
            if c.get("ragas") and c["ragas"].get(key) is not None
        ]
        summary[f"{key}_mean"] = round(sum(values) / len(values), 4) if values else None
        summary[f"{key}_count"] = len(values)
    summary["evaluated_cases"] = sum(1 for c in per_case if c.get("ragas") and not c["ragas"].get("skipped"))
    summary["skipped_cases"] = sum(1 for c in per_case if c.get("ragas", {}).get("skipped"))
    return summary


def merge_ragas_scores(
    rows: list[dict[str, Any]],
    questions: list[EvalQuestion],
    *,
    metric_names: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """
    Run RAGAS on live eval rows and attach per-case `ragas` objects.
    Returns (updated_rows, ragas_summary, ragas_meta).
    """
    metric_names = list(metric_names or DEFAULT_METRIC_NAMES)
    questions_by_id = {q.id: q for q in questions}
    updated = [dict(r) for r in rows]

    for row in updated:
        qid = str(row.get("id") or "")
        item = questions_by_id.get(qid)
        if item is None or not item.reference_answer:
            row["ragas"] = {
                "skipped": True,
                "ragas_skipped_reason": "missing_reference_answer",
            }
        elif row.get("error"):
            row["ragas"] = {
                "skipped": True,
                "ragas_skipped_reason": "request_error",
                "ragas_error": row.get("error"),
            }

    dataset, row_indices = build_hf_dataset(updated, questions_by_id)
    names_normalized = [n.strip().lower() for n in metric_names]

    meta: dict[str, Any] = {
        "ragas_enabled": True,
        "metrics": names_normalized,
    }

    if dataset is None or len(row_indices) == 0:
        meta["ragas_error"] = "no_evaluable_cases"
        summary = aggregate_ragas_summary(updated, names_normalized)
        return updated, summary, meta

    try:
        data, llm_model, emb_model = _execute_ragas_subprocess(dataset, names_normalized, env=env)
        meta["ragas_model"] = llm_model
        meta["ragas_embedding_model"] = emb_model
        meta["ragas_package_scores"] = {
            k: _safe_float(v) for k, v in (data.get("package_scores") or {}).items() if _safe_float(v) is not None
        }
        df_rows = data.get("rows") or []
    except Exception as exc:
        meta["ragas_error"] = str(exc)
        for row in updated:
            if row.get("ragas") is None:
                row["ragas"] = {"skipped": True, "ragas_error": str(exc)}
        summary = aggregate_ragas_summary(updated, names_normalized)
        return updated, summary, meta

    for i, src_idx in enumerate(row_indices):
        row_scores = df_rows[i] if i < len(df_rows) else {}
        scores: dict[str, Any] = {"skipped": False}
        for name in names_normalized:
            if name in row_scores:
                scores[name] = _safe_float(row_scores[name])
        updated[src_idx]["ragas"] = scores

    summary = aggregate_ragas_summary(updated, names_normalized)
    return updated, summary, meta