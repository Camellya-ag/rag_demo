from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.scripts.run_eval import _extract_answer, build_eval_metadata, resolve_code_version


class RunEvalMetadataTests(unittest.TestCase):
    def test_final_empty_hits_override_intermediate_hits(self) -> None:
        events = [
            {"type": "hits", "hits": [{"id": "discarded_evidence"}]},
            {"type": "answer", "text": "无法据此作答", "hits": [], "meta": {}},
        ]
        _, hits, _, _ = _extract_answer(events)
        self.assertEqual(hits, [])

    def test_resolve_code_version_from_git(self) -> None:
        with patch("backend.scripts.run_eval.subprocess.check_output", side_effect=["abc1234\n", " M backend/x\n"]):
            self.assertEqual(resolve_code_version({}), "abc1234-dirty")

    def test_build_eval_metadata_fields(self) -> None:
        with patch("backend.scripts.run_eval.resolve_index_version", return_value=("v20261124193025", "health")):
            with patch("backend.scripts.run_eval.resolve_code_version", return_value="abc1234"):
                meta = build_eval_metadata(
                    "http://127.0.0.1:8010",
                    Path(__file__).resolve().parents[1] / "data" / "eval" / "eval_questions.json",
                    env={"XIYOU_EVAL_MODEL": "qwen-flash"},
                )
        self.assertEqual(meta["index_version"], "v20261124193025")
        self.assertEqual(meta["index_version_source"], "health")
        self.assertEqual(meta["model"], "qwen-flash")
        self.assertEqual(meta["code_version"], "abc1234")
        self.assertTrue(meta["dataset_sha256"])
        _ = json.dumps(meta, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
