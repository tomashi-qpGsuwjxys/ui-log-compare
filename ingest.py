"""
routers/ingest.py
CSV 取込 API
DuckDB の read_csv() を使って取込パイプライン不要で直接インサート
"""
import hashlib
from pathlib import Path
from fastapi import APIRouter, HTTPException
from core.database import get_conn
from core.models import IngestRequest, IngestResponse

router = APIRouter(prefix="/ingest", tags=["ingest"])

REQUIRED_COLUMNS = {
    "project", "version", "err_code", "err_summary"
}


@router.post("", response_model=IngestResponse)
def ingest_csv(body: IngestRequest):
    filepath = Path(body.filepath)

    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")

    if filepath.suffix.lower() != ".csv":
        raise HTTPException(status_code=422, detail="File must be a .csv")

    conn = get_conn()

    # ── 1. スキーマ確認（必須カラムの存在チェック） ──────────────────────
    try:
        peek = conn.execute(f"""
            SELECT * FROM read_csv('{filepath}', header=true) LIMIT 1
        """)
        actual_cols = {d[0].lower() for d in peek.description}
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"CSV parse error: {e}")

    missing = REQUIRED_COLUMNS - actual_cols
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required columns: {missing}"
        )

    # ── 2. バージョン・プロジェクト特定 ──────────────────────────────────
    meta = conn.execute(f"""
        SELECT project, version, COUNT(*) AS cnt
        FROM read_csv('{filepath}', header=true)
        GROUP BY project, version
        ORDER BY cnt DESC
        LIMIT 1
    """).fetchone()

    if not meta:
        raise HTTPException(status_code=422, detail="CSV has no data rows")

    project, version, _ = meta

    # ── 3. 重複チェック ───────────────────────────────────────────────────
    exists = conn.execute(
        "SELECT COUNT(*) FROM versions WHERE version = ? AND project = ?",
        [version, project]
    ).fetchone()[0]

    if exists:
        return IngestResponse(
            success=False,
            version=version,
            project=project,
            rows=0,
            message=f"{project} / {version} は取込済みです。再取込の場合は先に既存データを削除してください。"
        )

    # ── 4. error_logs へ INSERT ───────────────────────────────────────────
    # DuckDB の read_csv() を直接 INSERT INTO に使う
    # err_key = MD5(project || err_code || err_summary) を生成
    conn.execute(f"""
        INSERT INTO error_logs
            (id, project, version, process_name, category, toolname,
             logpath, err_code, err_summary, err_key)
        SELECT
            nextval('seq_error_logs'),
            project,
            version,
            process_name,
            category,
            toolname,
            logpath,
            err_code,
            err_summary,
            md5(project || err_code || err_summary) AS err_key
        FROM read_csv('{filepath}', header=true, null_padding=true)
    """)

    row_count = conn.execute(
        "SELECT COUNT(*) FROM error_logs WHERE version = ? AND project = ?",
        [version, project]
    ).fetchone()[0]

    # ── 5. versions に登録 ────────────────────────────────────────────────
    conn.execute("""
        INSERT OR REPLACE INTO versions
            (version, project, imported_at, row_count, file_path)
        VALUES (?, ?, now(), ?, ?)
    """, [version, project, row_count, str(filepath)])

    return IngestResponse(
        success=True,
        version=version,
        project=project,
        rows=row_count,
        message=f"取込完了: {row_count}件"
    )


@router.delete("/{project}/{version}", response_model=IngestResponse)
def delete_version(project: str, version: str):
    """指定バージョンのデータを削除（再取込のため）"""
    conn = get_conn()

    count = conn.execute(
        "SELECT COUNT(*) FROM error_logs WHERE version = ? AND project = ?",
        [version, project]
    ).fetchone()[0]

    conn.execute(
        "DELETE FROM error_logs WHERE version = ? AND project = ?",
        [version, project]
    )
    conn.execute(
        "DELETE FROM versions WHERE version = ? AND project = ?",
        [version, project]
    )

    return IngestResponse(
        success=True,
        version=version,
        project=project,
        rows=count,
        message=f"削除完了: {count}件"
    )
