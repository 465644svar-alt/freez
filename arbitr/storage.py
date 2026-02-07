from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import RunResult


class Storage:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self._init_db()

    def _init_db(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                user_query TEXT NOT NULL,
                stage1_json TEXT NOT NULL,
                stage2_json TEXT NOT NULL,
                aggregation_json TEXT NOT NULL,
                final_answer TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def save_run(self, run: RunResult) -> None:
        self.conn.execute(
            """
            INSERT INTO runs (created_at, title, user_query, stage1_json, stage2_json, aggregation_json, final_answer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.created_at.isoformat(),
                run.title,
                run.user_query,
                json.dumps([s.__dict__ for s in run.stage1], ensure_ascii=False),
                json.dumps([s.__dict__ for s in run.stage2], ensure_ascii=False),
                json.dumps(run.aggregated.__dict__ if run.aggregated else {}, ensure_ascii=False),
                run.final_answer,
            ),
        )
        self.conn.commit()

    def list_runs(self) -> list[dict]:
        cur = self.conn.execute("SELECT id, created_at, title, user_query FROM runs ORDER BY id DESC")
        return [{"id": row[0], "created_at": row[1], "title": row[2], "user_query": row[3]} for row in cur.fetchall()]

    def get_run(self, run_id: int) -> dict | None:
        cur = self.conn.execute(
            "SELECT id, created_at, title, user_query, stage1_json, stage2_json, aggregation_json, final_answer FROM runs WHERE id = ?",
            (run_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "created_at": row[1],
            "title": row[2],
            "user_query": row[3],
            "stage1": json.loads(row[4]),
            "stage2": json.loads(row[5]),
            "aggregation": json.loads(row[6]),
            "final_answer": row[7],
        }
