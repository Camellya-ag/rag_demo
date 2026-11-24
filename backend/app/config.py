from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
RAG_ENV = ROOT.parent / "rag_examples" / ".env"
load_dotenv(RAG_ENV, override=False)

SOURCE_FILE = ROOT / "wmk" / "docs" / "西游记.txt"
STATE_FILE = ROOT / "backend" / "data" / "state.json"
JOBS_FILE = ROOT / "backend" / "data" / "jobs.json"
QA_PAIRS_FILE = ROOT / "backend" / "data" / "qa_pairs.json"

MILVUS_URI = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
API_PREFIX = "/api"
HOST = os.getenv("XIYOU_API_HOST", "127.0.0.1")
PORT = int(os.getenv("XIYOU_API_PORT", "8010"))

EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_DIM = 1024
LLM_MODEL_DEFAULT = os.getenv("XIYOU_LLM_MODEL", "qwen-flash")
QA_GEN_MODEL_DEFAULT = os.getenv("XIYOU_QA_GEN_MODEL", "qwen-flash")
def _resolve_rerank_model() -> str:
    """西游问典固定走百炼 TextReRank；勿误用 rag_examples 里本地 RERANK_MODEL 路径。"""
    dedicated = os.getenv("XIYOU_RERANK_MODEL", "").strip()
    if dedicated:
        return dedicated
    shared = os.getenv("RERANK_MODEL", "qwen3-rerank").strip()
    if shared and ("/" in shared or "\\" in shared or shared.endswith(".onnx")):
        return "qwen3-rerank"
    return shared or "qwen3-rerank"


RERANK_MODEL = _resolve_rerank_model()

CHUNK_SIZE = int(os.getenv("XIYOU_CHUNK_SIZE", "512"))
CHUNK_OVERLAP = int(os.getenv("XIYOU_CHUNK_OVERLAP", "64"))
RRF_K = 60
DEFAULT_TOP_K = 4
CANDIDATE_LIMIT = 16

SAMPLE_CHAPTER_LIMIT = int(os.getenv("XIYOU_SAMPLE_CHAPTERS", "3"))
SAMPLE_CHUNK_LIMIT = int(os.getenv("XIYOU_SAMPLE_CHUNKS", "48"))

PRICING_REGION = os.getenv("XIYOU_PRICING_REGION", "cn-beijing")
PRICING_UPDATED_AT = os.getenv("XIYOU_PRICING_UPDATED_AT", "2026-11-24")
PRICING_SOURCE = os.getenv(
    "XIYOU_PRICING_SOURCE",
    "help.aliyun.com/zh/model-studio/model-pricing（华北2北京，≤128K 档）",
)


def _model_slug(model: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", model).strip("_").upper()


def _rate(name: str, fallback: str | None) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return float(fallback) if fallback is not None else None
    try:
        return float(raw)
    except ValueError:
        return None


PRICING = {
    "region": PRICING_REGION,
    "updated_at": PRICING_UPDATED_AT,
    "source": PRICING_SOURCE,
    "embedding_model": EMBEDDING_MODEL,
    # 元/千 tokens：北京原价 0.15/1.5、0.5、0.5 每百万 tokens → 见 backend/docs/PRICING.md
    "embedding_per_1k": _rate("PRICE_EMBED_PER_1K", "0.0005") or 0.0005,
    "rerank_model": RERANK_MODEL,
    "rerank_per_1k": _rate("PRICE_RERANK_PER_1K", "0.0005") or 0.0005,
    "default_llm_model": LLM_MODEL_DEFAULT,
    "llm_input_per_1k": _rate("PRICE_LLM_QWEN_FLASH_IN_PER_1K", "0.00015") or 0.00015,
    "llm_output_per_1k": _rate("PRICE_LLM_QWEN_FLASH_OUT_PER_1K", "0.0015") or 0.0015,
}


def resolve_llm_pricing(model: str | None = None) -> tuple[str, float | None, float | None]:
    model_name = (model or LLM_MODEL_DEFAULT).strip() or LLM_MODEL_DEFAULT
    slug = _model_slug(model_name)
    in_rate = _rate(f"PRICE_LLM_{slug}_IN_PER_1K", None)
    out_rate = _rate(f"PRICE_LLM_{slug}_OUT_PER_1K", None)
    if in_rate is None:
        in_rate = _rate("PRICE_LLM_IN_PER_1K", None)
    if out_rate is None:
        out_rate = _rate("PRICE_LLM_OUT_PER_1K", None)
    if model_name == LLM_MODEL_DEFAULT and in_rate is None:
        in_rate = PRICING["llm_input_per_1k"]
    if model_name == LLM_MODEL_DEFAULT and out_rate is None:
        out_rate = PRICING["llm_output_per_1k"]
    return model_name, in_rate, out_rate


def pricing_snapshot() -> dict[str, object]:
    models = {}
    for model in sorted({LLM_MODEL_DEFAULT, QA_GEN_MODEL_DEFAULT, "qwen-plus", "qwen-turbo"}):
        _, in_rate, out_rate = resolve_llm_pricing(model)
        models[model] = {
            "input_per_1k": in_rate,
            "output_per_1k": out_rate,
            "usage_known": in_rate is not None and out_rate is not None,
        }
    return {
        "region": PRICING_REGION,
        "updated_at": PRICING_UPDATED_AT,
        "source": PRICING_SOURCE,
        "currency": "CNY",
        "embedding": {"model": EMBEDDING_MODEL, "per_1k": PRICING["embedding_per_1k"]},
        "rerank": {"model": RERANK_MODEL, "per_1k": PRICING["rerank_per_1k"]},
        "llm_models": models,
        "default_llm_model": LLM_MODEL_DEFAULT,
        "qa_gen_model": QA_GEN_MODEL_DEFAULT,
    }

CORS_ORIGINS = [
    "http://127.0.0.1:5180",
    "http://localhost:5180",
    "http://127.0.0.1:3333",
    "http://localhost:3333",
]

QA_PAIRS_JSONL = ROOT / "backend" / "data" / "qa_pairs.jsonl"
QA_PAIRS_SNAPSHOT_DIR = ROOT / "backend" / "data" / "qa_snapshots"
QA_PAIRS_FIXTURE = ROOT / "backend" / "data" / "fixtures" / "qa_pairs.sample.jsonl"
QA_PAIRS_ENABLED = os.getenv("XIYOU_QA_PAIRS_ENABLED", "true").lower() in {"1", "true", "yes"}
QA_PAIR_MAX = int(os.getenv("XIYOU_QA_PAIR_MAX", "512"))
QA_QUESTIONS_PER_CHAPTER = int(os.getenv("XIYOU_QA_QUESTIONS_PER_CHAPTER", "3"))
QA_AUTO_GENERATE = os.getenv("XIYOU_QA_AUTO_GENERATE", "false").lower() in {"1", "true", "yes"}
ALLOW_DEV_SAMPLE_INDEX = os.getenv("XIYOU_ALLOW_DEV_SAMPLE", "true").lower() in {"1", "true", "yes"}
