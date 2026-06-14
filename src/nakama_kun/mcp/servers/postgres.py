from __future__ import annotations

import os
import sqlite3
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("postgres")


def _is_mock() -> bool:
    host = os.environ.get("POSTGRES_HOST")
    user = os.environ.get("POSTGRES_USER")
    return not host or not user or os.environ.get("POSTGRES_MOCK") == "true"


def _get_sqlite_conn() -> sqlite3.Connection:
    db_path = os.environ.get("POSTGRES_SQLITE_PATH") or ":memory:"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount REAL
        );
    """)
    conn.commit()
    return conn


@mcp.tool()
def postgres_query(query: str) -> str:
    """Execute a read-only SQL query on the database.

    Permissions: db_query
    Categories: database, postgres
    Usage: Run SELECT queries to inspect database state.
    """
    if _is_mock():
        try:
            conn = _get_sqlite_conn()
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description] if cursor.description else []
            conn.close()

            result = [f"Columns: {', '.join(cols)}"]
            for row in rows:
                result.append(str(row))
            return "\n".join(result)
        except Exception as e:
            return f"ERROR: SQLite mock query failed: {e}"

    host = os.environ.get("POSTGRES_HOST")
    port = os.environ.get("POSTGRES_PORT") or "5432"
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD") or ""
    db = os.environ.get("POSTGRES_DB") or "postgres"

    for driver in ["psycopg2", "psycopg", "pg8000"]:
        try:
            db_module = __import__(driver)
            if driver == "psycopg2" or driver == "pg8000":
                conn = db_module.connect(
                    host=host, port=int(port), user=user, password=password, database=db
                )
            elif driver == "psycopg":
                conn = db_module.connect(
                    host=host, port=int(port), user=user, password=password, dbname=db
                )
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description] if cursor.description else []
            conn.close()
            result = [f"Columns: {', '.join(cols)}"]
            for row in rows:
                result.append(str(row))
            return "\n".join(result)
        except ImportError:
            continue
        except Exception as e:
            return f"ERROR: Postgres query failed via {driver}: {e}"

    return "ERROR: No PostgreSQL driver installed."


@mcp.tool()
def postgres_describe_table(table_name: str) -> str:
    """Describe the schema of a specific table.

    Permissions: db_read
    Categories: database, postgres
    Usage: Retrieve column names and types for a table.
    """
    if _is_mock():
        try:
            conn = _get_sqlite_conn()
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name});")
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return f"Table '{table_name}' not found."

            result = []
            for row in rows:
                result.append(f"Column: {row[1]} - Type: {row[2]} (PK: {bool(row[5])})")
            return "\n".join(result)
        except Exception as e:
            return f"ERROR: SQLite mock describe failed: {e}"

    query = f"""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = '{table_name}';
    """
    return postgres_query(query)


@mcp.tool()
def postgres_list_tables() -> str:
    """List all user tables in the database.

    Permissions: db_read
    Categories: database, postgres
    Usage: Retrieve a list of all tables.
    """
    if _is_mock():
        try:
            conn = _get_sqlite_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            rows = cursor.fetchall()
            conn.close()
            tables = [row[0] for row in rows]
            return "\n".join(tables) if tables else "No tables found."
        except Exception as e:
            return f"ERROR: SQLite mock list tables failed: {e}"

    query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public';
    """
    return postgres_query(query)


if __name__ == "__main__":
    mcp.run()
