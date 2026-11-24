from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.app.ai.rag.evaluation import (
    aggregate_scores,
    load_eval_questions,
    passes_thresholds,
    score_case,
)


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
            if packet.get("hits"):
                hits = packet.get("hits") or hits
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
        row["trace_id"] = meta.get("trace_id")
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="运行西游问典固定评测集（会产生真实 API 费用）")
    parser.add_argument("--base-url", default=os.getenv("XIYOU_EVAL_BASE_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--limit", type=int, default=0, help="仅跑前 N 题，0 表示全量")
    parser.add_argument("--dataset", default="", help="自定义评测集 JSON 路径")
    parser.add_argument("--output", default="", help="结果输出路径，默认写到 backend/data/eval/results/")
    parser.add_argument("--fail-fast", action="store_true", help="阈值未达标时返回非 0")
    args = parser.parse_args()

    dataset_path = Path(args.dataset) if args.dataset else None
    questions = load_eval_questions(dataset_path)
    if args.limit > 0:
        questions = questions[: args.limit]

    rows = run_live(args.base_url, questions, streaming=False)
    summary = aggregate_scores(rows)
    ok, failures = passes_thresholds(summary)

    output_dir = Path(__file__).resolve().parents[1] / "data" / "eval" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.output) if args.output else output_dir / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "summary": summary,
        "threshold_ok": ok,
        "threshold_failures": failures,
        "cases": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"summary": summary, "threshold_ok": ok, "output": str(out)}, ensure_ascii=False, indent=2))
    if args.fail_fast and not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
