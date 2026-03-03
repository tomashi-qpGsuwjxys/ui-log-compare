"""
routers/export.py
レビュー済み結果を含むCSVエクスポート API
"""
import io
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from core.database import get_conn

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/{version}")
def export_csv(version: str, project: str | None = None):
    conn   = get_conn()
    params = [version]
    proj_cond = ""
    if project:
        proj_cond = "AND e.project = ?"
        params.append(project)

    rows = conn.execute(f"""
        SELECT
            e.project,
            e.version,
            e.process_name,
            e.category,
            e.toolname,
            e.logpath,
            e.err_code,
            e.err_summary,
            COALESCE(r.comment, '') AS comment,
            COALESCE(r.result,  '') AS result
        FROM error_logs e
        LEFT JOIN reviews r USING (err_key)
        WHERE e.version = ? {proj_cond}
        ORDER BY e.err_code
    """, params).fetchall()

    def to_csv(rows):
        header = "project,version,process_name,category,toolname,logpath," \
                 "err_code,err_summary,comment,result\n"
        yield header
        for row in rows:
            yield ",".join(
                f'"{str(v).replace(chr(34), chr(34)*2)}"' for v in row
            ) + "\n"

    filename = f"errorscope_{version}_{project or 'all'}.csv"
    return StreamingResponse(
        to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
