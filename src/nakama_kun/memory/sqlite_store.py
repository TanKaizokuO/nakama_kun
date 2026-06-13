from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from nakama_kun.memory.models import SuccessfulTask, FailureRecord, UserPreference


class MemoryStore:
    """Abstract store interface defining experience storage operations."""

    def save_success(self, task: SuccessfulTask) -> None:
        raise NotImplementedError

    def save_failure(self, failure: FailureRecord) -> None:
        raise NotImplementedError

    def save_preference(self, preference: UserPreference) -> None:
        raise NotImplementedError

    def get_successes(self) -> list[SuccessfulTask]:
        raise NotImplementedError

    def get_failures(self) -> list[FailureRecord]:
        raise NotImplementedError

    def get_preferences(self) -> list[UserPreference]:
        raise NotImplementedError


class SQLiteMemoryStore(MemoryStore):
    """SQLite-backed structured store implementation for local persistence."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialize_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_db(self) -> None:
        """Create necessary tables and perform schema migrations if necessary."""
        with self._connect() as conn:
            # 1. Migrate user_preferences if it exists with old key, value schema
            try:
                cursor = conn.execute("PRAGMA table_info(user_preferences);")
                columns = [row["name"] for row in cursor.fetchall()]
                if columns and "confidence" not in columns:
                    # Old schema detected, drop it to recreate with new columns
                    conn.execute("DROP TABLE user_preferences;")
            except Exception:
                pass

            # 2. Create tables
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS successful_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal TEXT NOT NULL,
                    plan_summary TEXT NOT NULL,
                    files_changed TEXT NOT NULL,
                    tools_used TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS failure_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal TEXT NOT NULL,
                    attempted_actions TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    failure_message TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # --- Success Tasks persistence ---

    def save_success(self, task: SuccessfulTask) -> None:
        files_json = json.dumps(task.files_changed)
        tools_json = json.dumps(task.tools_used)
        timestamp_str = task.timestamp.isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO successful_tasks (goal, plan_summary, files_changed, tools_used, outcome, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task.goal, task.plan_summary, files_json, tools_json, task.outcome, timestamp_str),
            )
            conn.commit()

    def get_successes(self) -> list[SuccessfulTask]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT goal, plan_summary, files_changed, tools_used, outcome, timestamp FROM successful_tasks ORDER BY timestamp DESC"
            )
            rows = cursor.fetchall()

        successes = []
        for r in rows:
            successes.append(
                SuccessfulTask(
                    goal=r["goal"],
                    plan_summary=r["plan_summary"],
                    files_changed=json.loads(r["files_changed"]),
                    tools_used=json.loads(r["tools_used"]),
                    outcome=r["outcome"],
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                )
            )
        return successes

    # --- Failure Records persistence ---

    def save_failure(self, failure: FailureRecord) -> None:
        actions_json = json.dumps(failure.attempted_actions)
        timestamp_str = failure.timestamp.isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO failure_records (goal, attempted_actions, failure_type, failure_message, resolution, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    failure.goal,
                    actions_json,
                    failure.failure_type,
                    failure.failure_message,
                    failure.resolution,
                    timestamp_str,
                ),
            )
            conn.commit()

    def get_failures(self) -> list[FailureRecord]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT goal, attempted_actions, failure_type, failure_message, resolution, timestamp FROM failure_records ORDER BY timestamp DESC"
            )
            rows = cursor.fetchall()

        failures = []
        for r in rows:
            failures.append(
                FailureRecord(
                    goal=r["goal"],
                    attempted_actions=json.loads(r["attempted_actions"]),
                    failure_type=r["failure_type"],
                    failure_message=r["failure_message"],
                    resolution=r["resolution"],
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                )
            )
        return failures

    # --- User Preferences persistence ---

    def save_preference(self, preference: UserPreference) -> None:
        timestamp_str = preference.updated_at.isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_preferences (key, value, confidence, source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    confidence=excluded.confidence,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (
                    preference.key,
                    preference.value,
                    preference.confidence,
                    preference.source,
                    timestamp_str,
                ),
            )
            conn.commit()

    def get_preferences(self) -> list[UserPreference]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT key, value, confidence, source, updated_at FROM user_preferences"
            )
            rows = cursor.fetchall()

        preferences = []
        for r in rows:
            preferences.append(
                UserPreference(
                    key=r["key"],
                    value=r["value"],
                    confidence=r["confidence"],
                    source=r["source"],
                    updated_at=datetime.fromisoformat(r["updated_at"]),
                )
            )
        return preferences
