from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.config import JOBS_FILE, STATE_FILE


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class StateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = self._load_json(STATE_FILE, self._default_state())
        self._jobs = self._load_json(JOBS_FILE, {})
        self._cancel_events: dict[str, threading.Event] = {}
        self._traces: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "active_version": None,
            "active_collection": None,
            "production_collection": None,
            "production_version": None,
            "sample_collection": None,
            "sample_version": None,
            "query_collection": None,
            "query_mode": "none",
            "chunk_count": 0,
            "indexed_at": None,
            "status": "idle",
            "progress": 0,
            "message": "尚未建立索引",
            "last_job_id": None,
        }

    def _load_json(self, path: Path, default: Any) -> Any:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
            return deepcopy(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return deepcopy(default)

    def _save_state(self) -> None:
        STATE_FILE.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_jobs(self) -> None:
        JOBS_FILE.write_text(json.dumps(self._jobs, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def update_state(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._state.update(patch)
            self._save_state()
            return deepcopy(self._state)

    def create_job(self, **fields: Any) -> dict[str, Any]:
        job_id = fields.get("job_id") or f"job_{uuid.uuid4().hex[:12]}"
        job = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "排队中",
            "cost_so_far": 0.0,
            "switched": False,
            "error": "",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            **fields,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._save_jobs()
            self.update_state({"status": "running", "progress": 0, "last_job_id": job_id, "message": "索引任务排队中"})
        return deepcopy(job)

    def update_job(self, job_id: str, **patch: Any) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            job.update(patch)
            self._jobs[job_id] = job
            self._save_jobs()
            return deepcopy(job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    def register_cancel(self, request_id: str) -> threading.Event:
        with self._lock:
            event = threading.Event()
            self._cancel_events[request_id] = event
            return event

    def cancel_request(self, request_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(request_id)
            if not event:
                return False
            event.set()
            return True

    def drop_cancel(self, request_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(request_id, None)

    def save_trace(self, trace_id: str, trace: dict[str, Any]) -> None:
        with self._lock:
            self._traces[trace_id] = deepcopy(trace)

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            trace = self._traces.get(trace_id)
            return deepcopy(trace) if trace else None


store = StateStore()
