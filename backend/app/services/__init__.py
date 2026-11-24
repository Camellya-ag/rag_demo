"""遗留兼容层：请从 backend.app.ai.rag 导入 RAG 组件。"""

from backend.app.ai.rag import (
    indexing_service,
    milvus_repo,
    qa_pair_store,
    rag_chat_service,
    source_loader,
    store,
)

__all__ = [
    "indexing_service",
    "milvus_repo",
    "qa_pair_store",
    "rag_chat_service",
    "source_loader",
    "store",
]
