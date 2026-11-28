from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.app.ai.rag.evaluation import (
    aggregate_scores,
    load_eval_questions,
    passes_thresholds,
    score_case,
)
from backend.app.ai.rag.ragas_eval import DEFAULT_METRIC_NAMES, merge_ragas_scores
from backend.app.config import LLM_MODEL_DEFAULT


def resolve_code_version(env: dict[str, str] | None = None) -> str:
    env = env or {}
    override = env.get("XIYOU_CODE_VERSION") or os.getenv("XIYOU_CODE_VERSION")
    if override:
        return override
    try:
        short = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=Path(__file__).resolve().parents[2],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if not short:
            return "unknown"
        return f"{short}{'-dirty' if dirty else ''}"
    except Exception:
        return "unknown"


def resolve_index_version(base_url: str) -> tuple[str | None, str]:
    health_url = base_url.rstrip("/") + "/api/health"
    try:
        with urllib.request.urlopen(health_url, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        version = payload.get("active_index_version") or payload.get("active_version")
        if version:
            return str(version), "health"
        return None, "health:missing_active_index_version"
    except urllib.error.URLError as exc:
        return None, f"health_unreachable:{exc.reason}"
    except Exception as exc:  # pragma: no cover - defensive fallback
        return None, f"health_error:{exc}"


def build_eval_metadata(
    base_url: str,
    dataset_path: Path | None = None,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = env or {}
    resolved_dataset = dataset_path or (Path(__file__).resolve().parents[1] / "data" / "eval" / "eval_questions.json")
    index_version, index_source = resolve_index_version(base_url)
    model = env.get("XIYOU_EVAL_MODEL") or os.getenv("XIYOU_EVAL_MODEL") or LLM_MODEL_DEFAULT
    return {
        "code_version": resolve_code_version(env),
        "model": model,
        "index_version": index_version,
        "index_version_source": index_source,
        "dataset_path": str(resolved_dataset),
        "dataset_sha256": _dataset_sha256(resolved_dataset),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": base_url,
    }


def _request_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _extract_answer(events: list[dict]) -> tuple[str, list[dict], dict, str | None]:
    hits: list[dict] = []
    answer = ""
    meta: dict = {}
    error = None
    for packet in events:
        ptype = packet.get("type")
        if ptype == "hits":
            hits = packet.get("hits") or []
        elif ptype == "answer":
            answer = str(packet.get("text") or "")
            meta = packet.get("meta") or {}
            if "hits" in packet:
                hits = packet.get("hits") or []
        elif ptype == "error":
            error = str(packet.get("message") or "unknown error")
    return answer, hits, meta, error


def run_live(base_url: str, questions, *, streaming: bool = False) -> list[dict]:
    endpoint = base_url.rstrip("/") + "/api/chat/query"
    rows: list[dict] = []
    for item in questions:
        started = time.perf_counter()
        latency_ms = 0
        try:
            payload = {
                "request_id": uuid.uuid4().hex,
                "question": item.question,
                "settings": {
                    "top_k": 4,
                    "temperature": 0.2,
                    "streaming": streaming,
                    "model": os.getenv("XIYOU_EVAL_MODEL") or LLM_MODEL_DEFAULT,
                },
                "messages": [],
            }
            result = _request_json(endpoint, payload)
            events = result.get("events") or []
            answer, hits, meta, error = _extract_answer(events)
            latency_ms = int((time.perf_counter() - started) * 1000)
        except urllib.error.URLError as exc:
            answer, hits, meta, error = "", [], {}, str(exc)

        row = score_case(item, hits=hits, answer=answer, error=error)
        row["latency_ms"] = latency_ms if latency_ms else int((time.perf_counter() - started) * 1000)
        row["cost"] = meta.get("cost")
        row["latency_total_ms"] = meta.get("total_latency")
        row["first_token_ms"] = meta.get("first_token_ms")
        row["trace_id"] = meta.get("trace_id")
        row["hits"] = hits
        rows.append(row)
    return rows


def _dataset_sha256(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="运行西游问典固定评测集（会产生真实 API 费用）")
    parser.add_argument("--base-url", default=os.getenv("XIYOU_EVAL_BASE_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--limit", type=int, default=0, help="仅跑前 N 题，0 表示全量")
    parser.add_argument("--dataset", default="", help="自定义评测集 JSON 路径")
    parser.add_argument("--output", default="", help="结果输出路径，默认写到 backend/data/eval/results/")
    parser.add_argument("--fail-fast", action="store_true", help="阈值未达标时返回非 0")
    parser.add_argument(
        "--ragas",
        action="store_true",
        help="在规则评分后运行 RAGAS 语义指标（额外 LLM/Embedding 费用）",
    )
    parser.add_argument(
        "--ragas-metrics",
        default=",".join(DEFAULT_METRIC_NAMES),
        help="逗号分隔的 RAGAS 指标名，默认全套",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset) if args.dataset else None
    questions = load_eval_questions(dataset_path)
    if args.limit > 0:
        questions = questions[: args.limit]

    rows = run_live(args.base_url, questions, streaming=False)
    summary = aggregate_scores(rows)
    ok, failures = passes_thresholds(summary)

    ragas_summary: dict[str, Any] | None = None
    ragas_meta: dict[str, Any] = {"ragas_enabled": False}
    if args.ragas:
        metric_names = [p.strip() for p in args.ragas_metrics.split(",") if p.strip()]
        rows, ragas_summary, ragas_meta = merge_ragas_scores(rows, questions, metric_names=metric_names)

    output_dir = Path(__file__).resolve().parents[1] / "data" / "eval" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.output) if args.output else output_dir / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    metadata = build_eval_metadata(args.base_url, dataset_path)
    payload = {
        **metadata,
        **ragas_meta,
        "summary": summary,
        "ragas_summary": ragas_summary,
        "ragas_thresholds": None,
        "threshold_ok": ok,
        "threshold_failures": failures,
        "metrics_note": "citation_ok 仅表示引用编号在当轮 hits 范围内，不代表语义证据充分。",
        "cases": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"summary": summary, "threshold_ok": ok, "output": str(out)}, ensure_ascii=False, indent=2))
    if args.fail_fast and not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
