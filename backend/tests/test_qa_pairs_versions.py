from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.services.qa_pairs import QAPairStore


class QaPairVersionTests(unittest.TestCase):
    def test_resolve_backfills_snapshot_for_active_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "qa_pairs.jsonl"
            legacy.write_text(json.dumps({"id": "1", "chapter": 1, "question": "q"}) + "\n", encoding="utf-8")
            snap_dir = Path(tmp) / "snapshots"
            state = {"active_version": "v20261124193025", "production_version": "v20261124193025"}
            with patch("backend.app.services.qa_pairs.QA_PAIRS_JSONL", legacy):
                with patch("backend.app.services.qa_pairs.QA_PAIRS_SNAPSHOT_DIR", snap_dir):
                    path = QAPairStore.resolve_snapshot_path("v20261124193025", state=state)
            self.assertEqual(path, snap_dir / "v20261124193025.jsonl")

    def test_version_snapshot_takes_precedence_over_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snap_dir = Path(tmp) / "snapshots"
            snap_dir.mkdir(parents=True)
            legacy = Path(tmp) / "qa_pairs.jsonl"
            versioned = snap_dir / "v_new.jsonl"
            legacy.write_text("{}", encoding="utf-8")
            versioned.write_text(json.dumps({"id": "2", "chapter": 1, "question": "q2"}) + "\n", encoding="utf-8")
            state = {"active_version": "v_new", "production_version": "v_new"}
            with patch("backend.app.services.qa_pairs.QA_PAIRS_JSONL", legacy):
                with patch("backend.app.services.qa_pairs.QA_PAIRS_SNAPSHOT_DIR", snap_dir):
                    path = QAPairStore.resolve_snapshot_path("v_new", state=state)
            self.assertEqual(path, versioned)

    def test_sync_skips_reload_when_version_unchanged(self) -> None:
        store = QAPairStore()
        store._loaded_version = "v1"
        store._loaded_collection = "c1"
        state = {
            "query_mode": "production",
            "production_version": "v1",
            "active_version": "v1",
            "query_collection": "c1",
        }
        with patch("backend.app.services.qa_pairs.store.get_state", return_value=state):
            with patch.object(store, "_load_records_for_state") as loader:
                store.sync_with_state()
        loader.assert_not_called()

    def test_materialize_legacy_snapshot_creates_version_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "qa_pairs.jsonl"
            legacy.write_text(json.dumps({"id": "1", "chapter": 1, "question": "q"}) + "\n", encoding="utf-8")
            snap_dir = Path(tmp) / "snapshots"
            snap_dir.mkdir(parents=True)
            state = {"active_version": "v1", "production_version": "v1"}
            with patch("backend.app.services.qa_pairs.QA_PAIRS_JSONL", legacy):
                with patch("backend.app.services.qa_pairs.QA_PAIRS_SNAPSHOT_DIR", snap_dir):
                    path = QAPairStore.resolve_snapshot_path("v1", state=state)
            self.assertEqual(path, snap_dir / "v1.jsonl")
            self.assertTrue((snap_dir / "v1.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
