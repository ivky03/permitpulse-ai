"""Small SQLite history store that complements LangGraph checkpoints."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.modeling.train import ROOT


load_dotenv()
STATE_DATABASE_PATH = Path(
    os.getenv(
        "PERMITPULSE_STATE_DB",
        str(ROOT / "artifacts" / "permitpulse_state.sqlite"),
    )
)
WORKSPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")


def normalize_workspace_id(value: str) -> str:
    workspace_id = value.strip()
    if not WORKSPACE_PATTERN.fullmatch(workspace_id):
        raise ValueError(
            "Workspace ID must be 3-64 characters using letters, numbers, '_' or '-'."
        )
    return workspace_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HistoryStore:
    def __init__(self, database_path: Path = STATE_DATABASE_PATH) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.setup()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def setup(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assessment_history (
                    thread_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS history_workspace_idx "
                "ON assessment_history (workspace_id, updated_at DESC)"
            )

    def create(
        self,
        workspace_id: str,
        request: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        workspace_id = normalize_workspace_id(workspace_id)
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO assessment_history (
                    thread_id, workspace_id, created_at, updated_at, status,
                    request_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["thread_id"],
                    workspace_id,
                    timestamp,
                    timestamp,
                    result["status"],
                    json.dumps(request, separators=(",", ":"), sort_keys=True),
                    json.dumps(result, separators=(",", ":"), sort_keys=True),
                ),
            )

    def update(self, workspace_id: str, result: dict[str, Any]) -> None:
        workspace_id = normalize_workspace_id(workspace_id)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE assessment_history
                SET updated_at = ?, status = ?, result_json = ?
                WHERE thread_id = ? AND workspace_id = ?
                """,
                (
                    utc_now(),
                    result["status"],
                    json.dumps(result, separators=(",", ":"), sort_keys=True),
                    result["thread_id"],
                    workspace_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError("Assessment was not found in this workspace.")

    def get(self, workspace_id: str, thread_id: str) -> dict[str, Any]:
        workspace_id = normalize_workspace_id(workspace_id)
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT created_at, updated_at, request_json, result_json
                FROM assessment_history
                WHERE workspace_id = ? AND thread_id = ?
                """,
                (workspace_id, thread_id),
            ).fetchone()
        if row is None:
            raise KeyError("Assessment was not found in this workspace.")
        result = json.loads(row["result_json"])
        result["request"] = json.loads(row["request_json"])
        result["created_at"] = row["created_at"]
        result["updated_at"] = row["updated_at"]
        return result

    def list(self, workspace_id: str, limit: int = 30) -> list[dict[str, Any]]:
        workspace_id = normalize_workspace_id(workspace_id)
        limit = max(1, min(int(limit), 100))
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT thread_id, created_at, updated_at, status,
                       request_json, result_json
                FROM assessment_history
                WHERE workspace_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        summaries = []
        for row in rows:
            request = json.loads(row["request_json"])
            result = json.loads(row["result_json"])
            prediction = result.get("assessment", {}).get("prediction", {})
            report = result.get("report_file", {})
            project = result.get("project_context", {})
            summaries.append(
                {
                    "thread_id": row["thread_id"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "status": row["status"],
                    "borough": request.get("borough"),
                    "job_type": request.get("job_type"),
                    "risk_level": prediction.get("risk_level"),
                    "delay_probability": prediction.get("delay_probability"),
                    "report_status": report.get("status", "not_generated"),
                    "project_name": project.get("project_name", "Unnamed project"),
                    "permit_needed_by": project.get("permit_needed_by"),
                    "mitigation_owner": project.get(
                        "mitigation_owner", "Unassigned"
                    ),
                    "review_status": project.get("review_status", "new"),
                }
            )
        return summaries
