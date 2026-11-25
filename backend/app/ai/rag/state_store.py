from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.config import JOBS_FILE, STATE_FILE

logger = logging.getLogger(__name__)


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
        paths_to_try = [path, path.with_suffix(path.suffix + ".bak")]
        last_error: Exception | None = None
        for target in paths_to_try:
            if not target.exists():
                continue
            try:
                return json.loads(target.read_text(encoding="utf-8"))
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise RuntimeError(f"状态文件损坏：{path}；{last_error}") from last_error
        return deepcopy(default)

    def _atomic_write(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            backup.write_text(text, encoding="utf-8")
        except OSError as exc:
            # The primary file is already committed; callers must publish that state in memory.
            logger.warning("状态已提交，但备份更新失败：%s (%s)", backup, exc)

    def _save_state(self) -> None:
        self._atomic_write(STATE_FILE, self._state)

    def _save_jobs(self) -> None:
        self._atomic_write(JOBS_FILE, self._jobs)

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def update_state(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            next_state = deepcopy(self._state)
            next_state.update(patch)
            try:
                self._atomic_write(STATE_FILE, next_state)
            except Exception:
                raise
            self._state = next_state
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
            next_jobs = deepcopy(self._jobs)
            next_jobs[job_id] = job
            try:
                self._atomic_write(JOBS_FILE, next_jobs)
            except Exception:
                raise
            self._jobs = next_jobs
        return deepcopy(job)

    def update_job(self, job_id: str, **patch: Any) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            next_job = deepcopy(job)
            next_job.update(patch)
            next_jobs = deepcopy(self._jobs)
            next_jobs[job_id] = next_job
            try:
                self._atomic_write(JOBS_FILE, next_jobs)
            except Exception:
                raise
            self._jobs = next_jobs
            return deepcopy(next_job)

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

    def recover_interrupted_jobs(self) -> dict[str, Any]:
        recovered: list[str] = []
        with self._lock:
            next_jobs = deepcopy(self._jobs)
            for job_id, job in list(next_jobs.items()):
                if str(job.get("status") or "") not in {"queued", "running"}:
                    continue
                next_job = deepcopy(job)
                next_job.update(
                    {
                        "status": "failed",
                        "message": "进程重启，索引任务已中断",
                        "error": "interrupted_by_restart",
                        "finished_at": _now(),
                        "current_stage": "failed",
                    }
                )
                next_jobs[job_id] = next_job
                recovered.append(job_id)
            if recovered:
                try:
                    self._atomic_write(JOBS_FILE, next_jobs)
                except Exception:
                    raise
                self._jobs = next_jobs
            next_state = deepcopy(self._state)
            if next_state.get("status") == "running":
                next_state.update(
                    {
                        "status": "ready" if next_state.get("active_collection") else "idle",
                        "progress": 100 if next_state.get("active_collection") else 0,
                        "message": "已恢复最近成功索引",
                    }
                )
                try:
                    self._atomic_write(STATE_FILE, next_state)
                except Exception:
                    raise
                self._state = next_state
        return {"recovered_jobs": recovered, "active_collection": self._state.get("active_collection")}


store = StateStore()
