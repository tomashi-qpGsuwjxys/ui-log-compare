"""
routers/errors.py
エラー一覧・統計・バージョン出現履歴 API

DuckDB の list() 集約関数でバージョン出現履歴を1クエリで取得する
"""
from fastapi import APIRouter, Query
from core.database import get_conn
from core.models import ErrorListResponse, ErrorLog, ErrorStats

router = APIRouter(prefix="/errors", tags=["errors"])

# ── 共通サブクエリ: エラーごとの出現バージョン一覧を集約 ──────────────
# appeared_in: そのerr_keyが出現した全バージョンのリスト
_APPEARED_SUBQ = """
    WITH appeared AS (
        SELECT
            err_key,
            list(DISTINCT version ORDER BY version) AS appeared_in
        FROM error_logs
        GROUP BY err_key
    )
"""


@router.get("", response_model=ErrorListResponse)
def list_errors(
    version:  str,
    project:  str | None  = None,
    q:        str | None  = None,
    filter:   str | None  = None,   # all | new | recurring | unreviewed
    page:     int         = Query(1,  ge=1),
    limit:    int         = Query(50, ge=1, le=200),
):
    conn   = get_conn()
    offset = (page - 1) * limit

    where  = ["e.version = ?"]
    params = [version]

    if project:
        where.append("e.project = ?")
        params.append(project)

    if q:
        where.append("""(
            e.err_code     ILIKE ?
            OR e.err_summary   ILIKE ?
            OR e.process_name  ILIKE ?
            OR e.category      ILIKE ?
            OR e.toolname      ILIKE ?
        )""")
        like = f"%{q}%"
        params += [like, like, like, like, like]

    # filter 条件は HAVING 句で処理
    having = ""
    if filter == "new":
        # 出現バージョンが選択バージョン1件のみ = 初出
        having = f"HAVING list_contains(a.appeared_in, '{version}') AND len(a.appeared_in) = 1"
    elif filter == "recurring":
        having = "HAVING len(a.appeared_in) > 1"
    elif filter == "unreviewed":
        having = "HAVING r.result IS NULL"

    where_clause = " AND ".join(where)

    sql = f"""
        {_APPEARED_SUBQ}
        SELECT
            e.id,
            e.project,
            e.version,
            e.process_name,
            e.category,
            e.toolname,
            e.logpath,
            e.err_code,
            e.err_summary,
            e.err_key,
            a.appeared_in,
            r.comment,
            r.result
        FROM error_logs e
        LEFT JOIN appeared   a USING (err_key)
        LEFT JOIN reviews    r USING (err_key)
        WHERE {where_clause}
        {having}
        ORDER BY e.err_code
        LIMIT ? OFFSET ?
    """
    params += [limit, offset]

    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.description]

    errors = []
    for row in rows:
        d = dict(zip(cols, row))
        # appeared_in は DuckDB の list 型 → Python list に変換済み
        if d["appeared_in"] is None:
            d["appeared_in"] = []
        errors.append(ErrorLog(**d))

    # 総件数（ページネーション用）
    count_sql = f"""
        {_APPEARED_SUBQ}
        SELECT COUNT(*) FROM error_logs e
        LEFT JOIN appeared a USING (err_key)
        LEFT JOIN reviews  r USING (err_key)
        WHERE {where_clause}
        {having}
    """
    total = conn.execute(count_sql, params[:-2]).fetchone()[0]

    return ErrorListResponse(data=errors, total=total, page=page, limit=limit)


@router.get("/stats", response_model=ErrorStats)
def get_stats(version: str, project: str | None = None):
    """
    指定バージョンの統計サマリーを返す
    DuckDB の FILTER 句で1クエリにまとめる
    """
    conn   = get_conn()
    params = [version]
    proj_cond = ""
    if project:
        proj_cond = "AND e.project = ?"
        params.append(project)

    sql = f"""
        WITH appeared AS (
            SELECT err_key,
                   list(DISTINCT version ORDER BY version) AS appeared_in
            FROM error_logs GROUP BY err_key
        )
        SELECT
            COUNT(*)                                           AS total,
            COUNT(*) FILTER (WHERE len(a.appeared_in) = 1)    AS new_count,
            COUNT(*) FILTER (WHERE len(a.appeared_in) > 1)    AS recurring,
            COUNT(*) FILTER (WHERE r.result IS NOT NULL)       AS reviewed
        FROM error_logs e
        LEFT JOIN appeared a USING (err_key)
        LEFT JOIN reviews  r USING (err_key)
        WHERE e.version = ? {proj_cond}
    """
    row = conn.execute(sql, params).fetchone()
    return ErrorStats(
        total=row[0], new_count=row[1],
        recurring=row[2], reviewed=row[3],
    )
