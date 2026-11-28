from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

RAGAS_KEYS = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_correctness",
)


def _load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _summary_rows(payload: dict[str, Any]) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = [
        ("评测时间", payload.get("created_at")),
        ("代码版本", payload.get("code_version")),
        ("索引版本", payload.get("index_version")),
        ("模型", payload.get("model")),
        ("RAGAS LLM", payload.get("ragas_model")),
        ("RAGAS Embedding", payload.get("ragas_embedding_model")),
        ("题目数", payload.get("summary", {}).get("total")),
        ("", ""),
        ("规则指标", ""),
        ("retrieval_hit_rate", payload.get("summary", {}).get("retrieval_hit_rate")),
        ("citation_rate", payload.get("summary", {}).get("citation_rate")),
        ("answer_rate", payload.get("summary", {}).get("answer_rate")),
        ("error_rate", payload.get("summary", {}).get("error_rate")),
        ("threshold_ok", payload.get("threshold_ok")),
        ("", ""),
        ("RAGAS 汇总", ""),
    ]
    rs = payload.get("ragas_summary") or {}
    for key in RAGAS_KEYS:
        rows.append((f"{key}_mean", rs.get(f"{key}_mean")))
        rows.append((f"{key}_count", rs.get(f"{key}_count")))
    pkg = payload.get("ragas_package_scores") or {}
    if pkg:
        rows.append(("", ""))
        rows.append(("RAGAS 包级均值", ""))
        for key in RAGAS_KEYS:
            rows.append((key, pkg.get(key)))
    if payload.get("ragas_error"):
        rows.append(("", ""))
        rows.append(("ragas_error", payload.get("ragas_error")))
    rows.append(("", ""))
    rows.append(("说明", payload.get("metrics_note")))
    return rows


def _case_table(cases: list[dict[str, Any]]) -> list[list[Any]]:
    header = [
        "id",
        "question",
        "tags",
        "retrieval_ok",
        "citation_ok",
        "has_answer",
        "chapter_ok",
        "keyword_ok",
        "hit_count",
        "latency_ms",
        "trace_id",
        *RAGAS_KEYS,
        "answer_text",
    ]
    body: list[list[Any]] = [header]
    for case in cases:
        ragas = case.get("ragas") or {}
        body.append(
            [
                case.get("id"),
                case.get("question"),
                ",".join(case.get("tags") or []),
                case.get("retrieval_ok"),
                case.get("citation_ok"),
                case.get("has_answer"),
                case.get("chapter_ok"),
                case.get("keyword_ok"),
                case.get("hit_count"),
                case.get("latency_ms"),
                case.get("trace_id"),
                *[ragas.get(k) for k in RAGAS_KEYS],
                case.get("answer_text"),
            ]
        )
    return body


def export_excel(payload: dict[str, Any], out_path: Path) -> Path:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise RuntimeError("请先安装: pip install openpyxl") from exc

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "汇总"
    ws_sum.append(["指标", "值"])
    for k, v in _summary_rows(payload):
        ws_sum.append([k, v])
    ws_sum["A1"].font = Font(bold=True)
    ws_sum["B1"].font = Font(bold=True)
    ws_sum.column_dimensions["A"].width = 28
    ws_sum.column_dimensions["B"].width = 72

    table = _case_table(payload.get("cases") or [])
    ws_cases = wb.create_sheet("题目明细")
    for row in table:
        ws_cases.append(row)
    if table:
        for cell in ws_cases[1]:
            cell.font = Font(bold=True)
        ncol = len(table[0])
        ans_col = get_column_letter(ncol)
        for col in range(1, ncol + 1):
            letter = get_column_letter(col)
            ws_cases.column_dimensions[letter].width = (
                48 if letter == "B" else 80 if letter == ans_col else 16
            )
        for cell in ws_cases[ans_col]:
            if cell.row > 1:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="将 run_eval 产出的 JSON 导出为 Excel")
    parser.add_argument("input", nargs="?", help="eval_*.json 路径")
    parser.add_argument("--output", "-o", default="", help="输出 xlsx 路径")
    args = parser.parse_args()
    default_dir = Path(__file__).resolve().parents[1] / "data" / "eval" / "results"
    if args.input:
        inp = Path(args.input)
    else:
        candidates = sorted(default_dir.glob("eval_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print("未找到评测结果 JSON", file=sys.stderr)
            return 1
        inp = candidates[0]
    if not inp.exists():
        print(f"文件不存在: {inp}", file=sys.stderr)
        return 1
    payload = _load_payload(inp)
    out = Path(args.output) if args.output else inp.with_suffix(".xlsx")
    path = export_excel(payload, out)
    print(json.dumps({"input": str(inp), "output": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())