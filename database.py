"""
core/database.py
DuckDB 接続管理（シングルトン）
同時書き込みなし前提のため read_write モードで単一接続を保持
"""
import os
import duckdb
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "./data/errorscope.duckdb")

# シングルトン接続
# 同時書き込みなし前提 → read_write モードで1接続を共有
_conn: duckdb.DuckDBPyConnection | None = None


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = duckdb.connect(DB_PATH, read_only=False)
        _init_schema(_conn)
    return _conn


def _init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """テーブルが存在しない場合に初期化する"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS versions (
            version      VARCHAR  NOT NULL,
            project      VARCHAR  NOT NULL,
            imported_at  TIMESTAMP DEFAULT now(),
            row_count    INTEGER,
            file_path    VARCHAR,
            PRIMARY KEY (version, project)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS error_logs (
            id           BIGINT PRIMARY KEY,
            project      VARCHAR,
            version      VARCHAR,
            process_name VARCHAR,
            category     VARCHAR,
            toolname     VARCHAR,
            logpath      VARCHAR,
            err_code     VARCHAR,
            err_summary  VARCHAR,
            err_key      VARCHAR  -- md5(project || err_code || err_summary)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            err_key     VARCHAR PRIMARY KEY,
            project     VARCHAR,
            comment     TEXT,
            result      VARCHAR,  -- OK / NG / WIP / NEW
            updated_at  TIMESTAMP DEFAULT now()
        )
    """)

    # インデックス
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_logs_version
        ON error_logs(version)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_logs_err_key
        ON error_logs(err_key)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_logs_project
        ON error_logs(project)
    """)
