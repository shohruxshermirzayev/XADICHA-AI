"""Vazifalar tarixi va sozlamalar — SQLite (lokal)."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .models import TaskRecord, TaskStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    language TEXT,
    instruction TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_started ON tasks(started_at DESC);
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Storage:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(_SCHEMA)

    def fail_stale_running(self) -> int:
        """Server qayta ishga tushganda yarim qolgan vazifalarni "bajarilmadi" deb belgilaydi."""
        n = 0
        for t in self.list_tasks(limit=1000):
            if t.status.value == "running":
                t.status = TaskStatus.failed
                t.final_message = t.final_message or "Server to'xtatilgani sababli tugallanmadi."
                self.save_task(t)
                n += 1
        return n

    def save_task(self, task: TaskRecord) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO tasks (id, started_at, mode, status, language, instruction, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task.id, task.started_at, task.mode.value, task.status.value, task.language,
                 task.instruction, task.model_dump_json()),
            )
            self._db.commit()

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return TaskRecord.model_validate_json(row[0]) if row else None

    def list_tasks(self, limit: int = 50) -> list[TaskRecord]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM tasks ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [TaskRecord.model_validate_json(r[0]) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall()
        counts = {s: c for s, c in rows}
        total = sum(counts.values())
        done = counts.get("success", 0) + counts.get("failed", 0)
        return {
            "total": total,
            "success": counts.get("success", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "success_rate": round(counts.get("success", 0) / done * 100, 1) if done else None,
        }

    def clear_history(self) -> int:
        with self._lock:
            n = self._db.execute("DELETE FROM tasks").rowcount
            self._db.commit()
        return n

    def get_pref(self, key: str, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_pref(self, key: str, value) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)",
                             (key, json.dumps(value)))
            self._db.commit()
