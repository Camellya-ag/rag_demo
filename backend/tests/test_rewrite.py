from __future__ import annotations

import unittest

from backend.app.ai.rag.rewrite import rewrite_query
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


if __name__ == "__main__":
    unittest.main()
