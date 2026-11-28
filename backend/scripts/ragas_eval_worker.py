from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT.parent / "rag_examples" / ".env", override=False)


def _patch_ragas_executor_for_py314() -> None:
    """Ragas 0.1.x calls asyncio.as_completed outside a running loop (breaks on 3.14)."""
    import asyncio

    from ragas.executor import Executor, RunConfig
    from tqdm.auto import tqdm

    def results(self: Executor) -> list:
        max_workers = (self.run_config or RunConfig()).max_workers

        async def _aresults() -> list:
            coros = [afunc(*args, **kwargs) for afunc, args, kwargs, _ in self.jobs]
            if max_workers == -1:
                futures = asyncio.as_completed(coros)
            else:
                semaphore = asyncio.Semaphore(max_workers)

                async def sema_coro(coro):
                    async with semaphore:
                        return await coro

                futures = asyncio.as_completed([sema_coro(c) for c in coros])
            out: list = []
            for future in tqdm(
                futures,
                desc=self.desc,
                total=len(self.jobs),
                leave=self.keep_progress_bar,
            ):
                out.append(await future)
            return out

        raw = asyncio.run(_aresults())
        return [r[1] for r in sorted(raw, key=lambda x: x[0])]

    Executor.results = results  # type: ignore[method-assign]


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: ragas_eval_worker.py <input.json> <output.json>", file=sys.stderr)
        return 2
    inp = Path(sys.argv[1])
    out = Path(sys.argv[2])
    payload = json.loads(inp.read_text(encoding="utf-8"))
    metric_names: list[str] = payload.get("metrics") or []
    rows_payload: dict[str, Any] = payload.get("rows") or {}

    from datasets import Dataset

    from backend.app.ai.rag.ragas_eval import build_ragas_clients, resolve_metrics

    dataset = Dataset.from_dict(rows_payload)
    llm, embeddings, llm_model, emb_model = build_ragas_clients()
    metrics = resolve_metrics(metric_names)
    from ragas import evaluate
    from ragas.run_config import RunConfig

    _patch_ragas_executor_for_py314()
    max_workers = int(os.getenv("XIYOU_RAGAS_MAX_WORKERS", "2"))
    timeout = int(os.getenv("XIYOU_RAGAS_TIMEOUT", "180"))
    run_config = RunConfig(max_workers=max_workers, timeout=timeout)
    result = evaluate(
        dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        run_config=run_config,
        raise_exceptions=False,
    )
    df = result.to_pandas()
    out_rows: list[dict[str, Any]] = []
    for _, series in df.iterrows():
        row_out = {}
        for col in df.columns:
            val = series[col]
            try:
                row_out[str(col)] = None if val != val else float(val)
            except (TypeError, ValueError):
                row_out[str(col)] = None
        out_rows.append(row_out)

    package_scores: dict[str, float] = {}
    try:
        for key in result.keys():
            val = result[key]
            if isinstance(val, (int, float)) and val == val:
                package_scores[str(key)] = float(val)
    except Exception:
        package_scores = {}

    out.write_text(
        json.dumps(
            {
                "rows": out_rows,
                "package_scores": package_scores,
                "ragas_model": llm_model,
                "ragas_embedding_model": emb_model,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())