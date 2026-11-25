from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.ai.rag.llm_client import llm_client
from backend.app.ai.rag.rewrite import rewrite_query


class PronounRewriteOfflineTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
