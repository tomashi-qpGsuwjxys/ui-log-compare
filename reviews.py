"""
routers/reviews.py
レビュー保存・取得 API
同時書き込みなし前提のため排他制御なし
"""
from fastapi import APIRouter, HTTPException
from core.database import get_conn
from core.models import Review, ReviewRequest

router = APIRouter(prefix="/reviews", tags=["reviews"])

VALID_RESULTS = {"OK", "NG", "WIP", "NEW", ""}


@router.get("/{err_key}", response_model=Review | None)
def get_review(err_key: str):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM reviews WHERE err_key = ?", [err_key]
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.description]
    return Review(**dict(zip(cols, row)))


@router.put("/{err_key}", response_model=Review)
def save_review(err_key: str, body: ReviewRequest):
    if body.result and body.result not in VALID_RESULTS:
        raise HTTPException(
            status_code=422,
            detail=f"result must be one of {VALID_RESULTS}"
        )

    conn = get_conn()

    # err_key からプロジェクト名を取得
    proj_row = conn.execute(
        "SELECT project FROM error_logs WHERE err_key = ? LIMIT 1",
        [err_key]
    ).fetchone()
    project = proj_row[0] if proj_row else None

    # INSERT OR REPLACE (upsert)
    conn.execute("""
        INSERT OR REPLACE INTO reviews (err_key, project, comment, result, updated_at)
        VALUES (?, ?, ?, ?, now())
    """, [err_key, project, body.comment, body.result])

    row  = conn.execute(
        "SELECT * FROM reviews WHERE err_key = ?", [err_key]
    ).fetchone()
    cols = [d[0] for d in conn.description]
    return Review(**dict(zip(cols, row)))
