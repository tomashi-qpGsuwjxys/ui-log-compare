"""
main.py
FastAPI エントリポイント
"""
import duckdb
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import get_conn
from routers import errors, versions, reviews, ingest, export


# ── シーケンス初期化（DuckDBのAUTO INCREMENT代替） ───────────────────────
def _init_sequences(conn: duckdb.DuckDBPyConnection):
    try:
        conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_error_logs START 1")
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_conn()
    _init_sequences(conn)
    print("✅ DuckDB connected:", conn.execute("SELECT version()").fetchone()[0])
    yield
    # シャットダウン時: DuckDB は接続を閉じるだけで永続化される
    conn.close()
    print("🦆 DuckDB connection closed")


# ── アプリ定義 ────────────────────────────────────────────────────────────
app = FastAPI(
    title="ErrorScope API",
    description="バージョンごとのCSVエラーログ管理・レビューシステム",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── ルーター登録 ──────────────────────────────────────────────────────────
app.include_router(versions.router)
app.include_router(errors.router)
app.include_router(reviews.router)
app.include_router(ingest.router)
app.include_router(export.router)


@app.get("/health")
def health():
    conn = get_conn()
    ver  = conn.execute("SELECT version()").fetchone()[0]
    tbl_count = conn.execute(
        "SELECT COUNT(*) FROM error_logs"
    ).fetchone()[0]
    return {
        "status":     "ok",
        "duckdb":     ver,
        "total_logs": tbl_count,
    }
