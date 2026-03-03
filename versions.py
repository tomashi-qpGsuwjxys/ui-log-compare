"""
routers/versions.py
バージョン一覧・統計 API
"""
from fastapi import APIRouter
from core.database import get_conn
from core.models import Version

router = APIRouter(prefix="/versions", tags=["versions"])


@router.get("", response_model=list[Version])
def list_versions(project: str | None = None):
    """
    バージョン一覧を昇順で返す
    DuckDB の自然ソートではバージョン文字列の順が保証されないため
    Python 側でソートする
    """
    conn = get_conn()
    query = "SELECT * FROM versions"
    params = []

    if project:
        query += " WHERE project = ?"
        params.append(project)

    rows = conn.execute(query, params).fetchall()
    cols = [d[0] for d in conn.description]
    versions = [Version(**dict(zip(cols, r))) for r in rows]

    # バージョン文字列を数値順にソート
    def ver_key(v: Version):
        parts = v.version.replace("v", "").replace("V", "").split(".")
        return [int(p) if p.isdigit() else 0 for p in parts]

    return sorted(versions, key=ver_key)
