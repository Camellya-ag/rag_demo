from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.ai.rag.rewrite import rewrite_query
from backend.app.ai.rag.llm_client import llm_client
from backend.app.utils.text import normalize_query_terms


class RewriteTests(unittest.TestCase):
    def test_houge_alias_rewrite(self) -> None:
        result = rewrite_query("猴哥为啥被压在五指山下")
        self.assertEqual(result["original"], "猴哥为啥被压在五指山下")
        self.assertIn("孙悟空", result["rewritten"])
        self.assertNotIn("猴哥", result["rewritten"])
        self.assertIn("为什么", result["rewritten"])
        self.assertTrue(result["changed"])
        self.assertIn("孙悟空", result["keywords"])
        self.assertIn("五指山", result["keywords"])

    def test_keywords_keep_wuzhishan(self) -> None:
        terms = normalize_query_terms("孙悟空为什么被压在五指山下")
        self.assertIn("五指山", terms)
        self.assertNotIn("指山下", terms)

    def test_canonical_names_not_polluted(self) -> None:
        self.assertEqual(rewrite_query("孙悟空为什么被压")["rewritten"], "孙悟空为什么被压")
        self.assertEqual(rewrite_query("猪八戒")["rewritten"], "猪八戒")
        result = rewrite_query("猴哥为啥被压在五指山下")
        self.assertIn("孙悟空", result["rewritten"])
        self.assertNotIn("孙孙", result["rewritten"])
        repeat = rewrite_query(result["rewritten"])
        self.assertEqual(repeat["rewritten"], result["rewritten"])

    @patch.object(llm_client, "_chat")
    def test_pronoun_followup_uses_history(self, chat_mock) -> None:
        chat_mock.return_value = type(
            "R",
            (),
            {"choices": [type("C", (), {"message": type("M", (), {"content": "猪八戒原来叫什么"})()})()]},
        )()
        result = rewrite_query(
            "他原来叫什么",
            [
                {"role": "user", "content": "猪八戒在天庭当过什么官？"},
                {"role": "assistant", "content": "他是天蓬元帅。"},
            ],
        )
        self.assertIn("猪八戒", result["rewritten"])
        self.assertIn("检索查询改写器", chat_mock.call_args.kwargs["system_prompt"])

    def test_pronoun_ambiguous_multi_entity(self) -> None:
        result = rewrite_query(
            "他原来叫什么",
            [
                {"role": "user", "content": "猪八戒和孙悟空是什么关系？"},
                {"role": "assistant", "content": "他们都是唐僧的徒弟。"},
            ],
        )
        self.assertEqual(result["rewritten"], "他原来叫什么")
        self.assertTrue(result["ambiguous_reference"])

    @patch.object(llm_client, "_chat")
    def test_llm_rewrite_uses_dedicated_system_prompt(self, chat_mock) -> None:
        chat_mock.return_value = type(
            "R",
            (),
            {"choices": [type("C", (), {"message": type("M", (), {"content": "猪八戒原来叫什么"})()})()]},
        )()
        rewrite_query("他原来叫什么", [{"role": "user", "content": "猪八戒在天庭当过什么官？"}])
        kwargs = chat_mock.call_args.kwargs
        self.assertIn("检索查询改写器", kwargs["system_prompt"])
        self.assertNotIn("无法据此作答", kwargs["system_prompt"])


if __name__ == "__main__":
    unittest.main()
