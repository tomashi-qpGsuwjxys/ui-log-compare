"""
core/models.py
Pydantic レスポンス / リクエストスキーマ
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ── Versions ────────────────────────────────────────────
class Version(BaseModel):
    version:     str
    project:     str
    imported_at: Optional[datetime] = None
    row_count:   Optional[int]      = None
    file_path:   Optional[str]      = None


# ── Error Logs ───────────────────────────────────────────
class ErrorLog(BaseModel):
    id:           int
    project:      str
    version:      str
    process_name: Optional[str] = None
    category:     Optional[str] = None
    toolname:     Optional[str] = None
    logpath:      Optional[str] = None
    err_code:     str
    err_summary:  Optional[str] = None
    err_key:      str
    # バージョン出現履歴（JOINで付与）
    appeared_in:  list[str]     = []
    # レビュー情報（JOINで付与）
    comment:      Optional[str] = None
    result:       Optional[str] = None


class ErrorListResponse(BaseModel):
    data:  list[ErrorLog]
    total: int
    page:  int
    limit: int


class ErrorStats(BaseModel):
    total:     int
    new_count: int
    recurring: int
    reviewed:  int


# ── Reviews ──────────────────────────────────────────────
class ReviewRequest(BaseModel):
    comment: Optional[str] = None
    result:  Optional[str] = None  # OK / NG / WIP / NEW


class Review(BaseModel):
    err_key:    str
    project:    Optional[str]      = None
    comment:    Optional[str]      = None
    result:     Optional[str]      = None
    updated_at: Optional[datetime] = None


# ── Ingest ───────────────────────────────────────────────
class IngestRequest(BaseModel):
    filepath: str  # サーバー上の絶対パス


class IngestResponse(BaseModel):
    success:  bool
    version:  Optional[str] = None
    project:  Optional[str] = None
    rows:     int           = 0
    message:  str           = ""
