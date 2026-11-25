from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.ai.rag.state_store import StateStore


class StateStoreTests(unittest.TestCase):
    def test_atomic_write_keeps_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            jobs_path = Path(tmp) / "jobs.json"
            with patch("backend.app.ai.rag.state_store.STATE_FILE", state_path), patch("backend.app.ai.rag.state_store.JOBS_FILE", jobs_path):
                store = StateStore()
                store.update_state({"status": "ready", "active_collection": "old", "active_version": "v1"})
                self.assertTrue(state_path.with_suffix(state_path.suffix + ".bak").exists())
                payload = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["active_collection"], "old")

    def test_recover_interrupted_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            jobs_path = Path(tmp) / "jobs.json"
            jobs_path.write_text(
                json.dumps(
                    {"job_a": {"job_id": "job_a", "status": "running", "progress": 10, "message": "running"}},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps({"status": "running", "active_collection": "old", "active_version": "v1"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with patch("backend.app.ai.rag.state_store.STATE_FILE", state_path), patch("backend.app.ai.rag.state_store.JOBS_FILE", jobs_path):
                store = StateStore()
                recovered = store.recover_interrupted_jobs()
                self.assertEqual(recovered["recovered_jobs"], ["job_a"])
                self.assertEqual(store.get_job("job_a")["status"], "failed")
                self.assertEqual(store.get_state()["active_collection"], "old")

    def test_corrupt_main_state_recovers_from_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            backup_path = state_path.with_suffix(state_path.suffix + ".bak")
            jobs_path = Path(tmp) / "jobs.json"
            backup_path.write_text(
                json.dumps({"status": "ready", "active_collection": "old", "active_version": "v1"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            state_path.write_text("not-json", encoding="utf-8")
            with patch("backend.app.ai.rag.state_store.STATE_FILE", state_path), patch("backend.app.ai.rag.state_store.JOBS_FILE", jobs_path):
                store = StateStore()
                self.assertEqual(store.get_state()["active_collection"], "old")
                self.assertEqual(store.get_state()["status"], "ready")

    def test_backup_write_failure_keeps_committed_state_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            jobs_path = Path(tmp) / "jobs.json"
            with patch("backend.app.ai.rag.state_store.STATE_FILE", state_path), patch("backend.app.ai.rag.state_store.JOBS_FILE", jobs_path):
                store = StateStore()
                real_write = Path.write_text

                def guarded_write(self, text, *args, **kwargs):
                    if self.name.endswith("state.json.bak"):
                        raise OSError("backup denied")
                    return real_write(self, text, *args, **kwargs)

                with patch.object(Path, "write_text", guarded_write):
                    store.update_state({"status": "ready", "active_collection": "good", "active_version": "v_good"})
                state = store.get_state()
                self.assertEqual(state["active_collection"], "good")
                self.assertEqual(state["status"], "ready")
                payload = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["active_collection"], "good")

