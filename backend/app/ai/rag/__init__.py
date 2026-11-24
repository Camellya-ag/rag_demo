"""西游问典 RAG 管线（对齐 base_fastapi_ai app/ai/rag）。"""

from backend.app.ai.rag.indexing import indexing_service
from backend.app.ai.rag.milvus_repo import milvus_repo
from backend.app.ai.rag.qa_pairs import qa_pair_store
from backend.app.ai.rag.rag_chat import rag_chat_service
from backend.app.ai.rag.source_loader import source_loader
from backend.app.ai.rag.state_store import store

__all__ = [
    "indexing_service",
    "milvus_repo",
    "qa_pair_store",
    "rag_chat_service",
    "source_loader",
    "store",
]
