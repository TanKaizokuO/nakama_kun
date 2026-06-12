from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from nakama_kun.ai.models.message import Message
from nakama_kun.memory.interfaces import MemoryRepository


class SQLiteMemoryRepository(MemoryRepository):
    """SQLite-backed memory repository for local persistent storage."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialize_db()

    def _connect(self) -> sqlite3.Connection:
        """Establish a connection to the SQLite database and enable foreign keys."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Enable foreign key support
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _initialize_db(self) -> None:
        """Create database tables if they do not exist."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    name TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT UNIQUE NOT NULL,
                    summary TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_metadata (
                    id TEXT PRIMARY KEY,
                    task_description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Conversations & Messages
    # ------------------------------------------------------------------

    def create_conversation(self, title: str, mode: str) -> str:
        conv_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, mode) VALUES (?, ?, ?, ?)",
                (conv_id, title, created_at, mode),
            )
            conn.commit()
        return conv_id

    def get_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id, title, created_at, mode FROM conversations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_conversation(self, mode: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id, title, created_at, mode FROM conversations WHERE mode = ? ORDER BY created_at DESC LIMIT 1",
                (mode,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_message(self, conversation_id: str, message: Message) -> None:
        # Serialize tool_calls list if present
        tool_calls_json = None
        if message.tool_calls is not None:
            tool_calls_json = json.dumps([tc.model_dump() for tc in message.tool_calls])

        timestamp_str = message.timestamp.isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, name, tool_calls, tool_call_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    message.role,
                    message.content,
                    message.name,
                    tool_calls_json,
                    message.tool_call_id,
                    timestamp_str,
                ),
            )
            conn.commit()

    def get_messages(self, conversation_id: str) -> list[Message]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT role, content, name, tool_calls, tool_call_id, timestamp
                FROM messages WHERE conversation_id = ? ORDER BY id ASC
                """,
                (conversation_id,),
            )
            rows = cursor.fetchall()

        messages = []
        for row in rows:
            # Parse tool_calls if stored
            tool_calls = None
            if row["tool_calls"]:
                tool_calls = json.loads(row["tool_calls"])

            timestamp = datetime.fromisoformat(row["timestamp"])

            # Map fields safely into Message Pydantic model
            msg = Message(
                role=row["role"],
                content=row["content"],
                name=row["name"],
                tool_calls=tool_calls,
                tool_call_id=row["tool_call_id"],
                timestamp=timestamp,
            )
            messages.append(msg)
        return messages

    def clear_conversation(self, conversation_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            conn.commit()

    def clear_all_conversations(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM conversations")
            conn.commit()

    # ------------------------------------------------------------------
    # Project Context Summaries
    # ------------------------------------------------------------------

    def save_project_summary(self, project_name: str, summary: str) -> None:
        analyzed_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_summaries (project_name, summary, analyzed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(project_name) DO UPDATE SET
                    summary=excluded.summary,
                    analyzed_at=excluded.analyzed_at
                """,
                (project_name, summary, analyzed_at),
            )
            conn.commit()

    def get_project_summary(self, project_name: str) -> str | None:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT summary FROM project_summaries WHERE project_name = ?",
                (project_name,),
            )
            row = cursor.fetchone()
            return row["summary"] if row else None

    # ------------------------------------------------------------------
    # User Preferences
    # ------------------------------------------------------------------

    def save_preference(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_preferences (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def get_preference(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT value FROM user_preferences WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            return row["value"] if row else default

    def delete_preference(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM user_preferences WHERE key = ?", (key,))
            conn.commit()

    def get_all_preferences(self) -> dict[str, str]:
        with self._connect() as conn:
            cursor = conn.execute("SELECT key, value FROM user_preferences")
            return {row["key"]: row["value"] for row in cursor.fetchall()}

    # ------------------------------------------------------------------
    # Agent Tasks Metadata
    # ------------------------------------------------------------------

    def save_task_metadata(
        self,
        task_id: str,
        description: str,
        status: str,
        finished_at: datetime | None = None,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        finished_at_str = finished_at.isoformat() if finished_at else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_metadata (id, task_description, status, created_at, finished_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    finished_at=excluded.finished_at
                """,
                (task_id, description, status, created_at, finished_at_str),
            )
            conn.commit()

    def get_task_metadata(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id, task_description, status, created_at, finished_at FROM task_metadata WHERE id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id, task_description, status, created_at, finished_at FROM task_metadata ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Global Wipes
    # ------------------------------------------------------------------

    def clear_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM conversations")
            conn.execute("DELETE FROM project_summaries")
            conn.execute("DELETE FROM user_preferences")
            conn.execute("DELETE FROM task_metadata")
            conn.commit()
