from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.ai.rag.rag_chat import RagChatService
from backend.app.utils.pricing import Usage


class RagChatPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RagChatService()
        self.events: list[tuple[str, dict]] = []

    def emit(self, key: str, patch: dict) -> None:
        self.events.append((key, patch))

    @patch("backend.app.ai.rag.rag_chat.store")
    @patch("backend.app.ai.rag.rag_chat.llm_client")
    @patch("backend.app.ai.rag.rag_chat.rerank_client")
    @patch("backend.app.ai.rag.rag_chat.qa_pair_store")
    @patch("backend.app.ai.rag.rag_chat.milvus_repo")
    @patch("backend.app.ai.rag.rag_chat.embedding_client")
    @patch("backend.app.ai.rag.rag_chat.rewrite_query")
    def test_same_query_reuses_embedding_and_sparse(
        self,
        rewrite_query,
        embedding_client,
        milvus_repo,
        qa_pair_store,
        rerank_client,
        llm_client,
        state_store,
    ) -> None:
        rewrite_query.return_value = {
            "original": "孙悟空怎么出生",
            "rewritten": "孙悟空怎么出生",
            "keywords": ["孙悟空"],
        }
        embedding_client.embed.return_value = ([[0.1, 0.2]], Usage(total_tokens=8, known=True))
        milvus_repo.count.return_value = 1
        milvus_repo.hybrid_search.return_value = (
            [{"id": "c1", "rank": 1, "score": 0.9, "text": "仙石", "chapter": 1, "chapter_title": "第一回", "tokens": 2, "source": "x"}],
            [{"id": "c1", "rank": 1, "score": 0.8, "text": "仙石", "chapter": 1, "chapter_title": "第一回", "tokens": 2, "source": "x"}],
            [{"id": "c1", "rank": 1, "score": 0.95, "text": "仙石", "chapter": 1, "chapter_title": "第一回", "tokens": 2, "source": "x"}],
        )
        qa_pair_store.enabled = False
        milvus_repo.rrf_fuse_channels.return_value = [
            {"id": "c1", "rank": 1, "score": 0.9, "text": "仙石", "chapter": 1, "chapter_title": "第一回", "tokens": 2, "source": "x"}
        ]
        rerank_client.score.return_value = ([0.9], Usage(total_tokens=5, known=True))
        llm_client.complete.return_value = ("答案[1]", Usage(input_tokens=10, output_tokens=2, known=True))
        state_store.get_state.return_value = {"query_collection": "coll"}

        result = self.service.run(
            {"question": "孙悟空怎么出生", "settings": {"streaming": False, "top_k": 1}},
            self.emit,
        )

        embedding_client.embed.assert_called_once()
        self.assertEqual(milvus_repo.hybrid_search.call_count, 1)
        self.assertIn("budget_stats", result["trace"]["stages"]["assemble"]["detail"])
        self.assertIn("generation_question", result["trace"]["stages"]["assemble"]["detail"])

    @patch("backend.app.ai.rag.rag_chat.store")
    @patch("backend.app.ai.rag.rag_chat.llm_client")
    @patch("backend.app.ai.rag.rag_chat.rerank_client")
    @patch("backend.app.ai.rag.rag_chat.qa_pair_store")
    @patch("backend.app.ai.rag.rag_chat.milvus_repo")
    @patch("backend.app.ai.rag.rag_chat.embedding_client")
    @patch("backend.app.ai.rag.rag_chat.rewrite_query")
    def test_budget_limits_assembled_hits(
        self,
        rewrite_query,
        embedding_client,
        milvus_repo,
        qa_pair_store,
        rerank_client,
        llm_client,
        state_store,
    ) -> None:
        rewrite_query.return_value = {"original": "x", "rewritten": "x", "keywords": []}
        embedding_client.embed.return_value = ([[0.1]], Usage(total_tokens=3, known=True))
        long = "长" * 700
        rows = [
            {"id": f"c{i}", "rank": i, "score": 1 - i * 0.1, "text": long, "chapter": 1, "chapter_title": "第一回", "tokens": 700, "source": "x"}
            for i in range(1, 4)
        ]
        milvus_repo.count.return_value = 1
        milvus_repo.hybrid_search.return_value = (rows[:1], rows[:1], rows)
        qa_pair_store.enabled = False
        milvus_repo.rrf_fuse_channels.return_value = rows
        rerank_client.score.return_value = ([0.9, 0.8, 0.7], Usage(total_tokens=5, known=True))
        llm_client.complete.return_value = ("答案[1]", Usage(input_tokens=10, output_tokens=2, known=True))
        state_store.get_state.return_value = {"query_collection": "coll"}

        result = self.service.run({"question": "x", "settings": {"streaming": False, "top_k": 3}}, self.emit)
        selected = result["trace"]["stages"]["assemble"]["detail"]["selected_count"]
        self.assertLess(selected, 3)

    @patch("backend.app.ai.rag.rag_chat.store")
    @patch("backend.app.ai.rag.rag_chat.llm_client")
    @patch("backend.app.ai.rag.rag_chat.rerank_client")
    @patch("backend.app.ai.rag.rag_chat.qa_pair_store")
    @patch("backend.app.ai.rag.rag_chat.milvus_repo")
    @patch("backend.app.ai.rag.rag_chat.embedding_client")
    @patch("backend.app.ai.rag.rag_chat.rewrite_query")
    def test_budget_selected_hits_align_with_returns(self, rewrite_query, embedding_client, milvus_repo, qa_pair_store, rerank_client, llm_client, state_store):
        rewrite_query.return_value = {"original": "q", "rewritten": "q", "keywords": []}
        embedding_client.embed.return_value = ([[0.1]], Usage(total_tokens=3, known=True))
        long = "文" * 1200
        rows = [
            {"id": "c1", "rank": 1, "score": 0.9, "text": long, "chapter": 1, "chapter_title": "第一回", "tokens": 1200, "source": "x"},
            {"id": "c2", "rank": 2, "score": 0.8, "text": "短片段", "chapter": 2, "chapter_title": "第二回", "tokens": 10, "source": "x"},
        ]
        milvus_repo.count.return_value = 1
        milvus_repo.hybrid_search.return_value = (rows, rows, rows)
        qa_pair_store.enabled = False
        milvus_repo.rrf_fuse_channels.return_value = rows
        rerank_client.score.return_value = ([0.9, 0.8], Usage(total_tokens=4, known=True))
        llm_client.complete.return_value = ("答案[1]", Usage(input_tokens=10, output_tokens=2, known=True))
        state_store.get_state.return_value = {"query_collection": "coll"}
        huge_prompt = "纲" * 2000
        result = self.service.run(
            {"question": "q", "settings": {"streaming": False, "top_k": 2, "system_prompt": huge_prompt}},
            self.emit,
        )
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(result["hits"][0]["id"], "c2")
        self.assertIn("短片段", result["hits"][0]["chunk"]["text"])
        self.assertGreater(result["hits"][0]["chunk"]["tokens"], 0)
        prompt = result["trace"]["stages"]["assemble"]["detail"]["prompt"]
        self.assertIn("短片段", prompt)
        llm_client.complete.assert_called_once()
        sent_prompt = llm_client.complete.call_args.args[0]
        self.assertIn("短片段", sent_prompt)

