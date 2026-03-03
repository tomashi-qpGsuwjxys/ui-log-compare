# ErrorScope — DuckDB Edition

バージョンごとのCSVエラーログを管理・レビューするダッシュボード。
**DuckDB + FastAPI + React** 構成で、Docker不要・単一ファイルDBで動作します。

---

## ディレクトリ構成

```
errorscope/
├── backend/
│   ├── main.py               # FastAPI エントリポイント
│   ├── watcher.py            # CSVファイル自動取込
│   ├── requirements.txt
│   ├── core/
│   │   ├── database.py       # DuckDB接続管理（シングルトン）
│   │   ├── models.py         # Pydanticスキーマ
│   │   └── schema.py         # テーブル定義
│   └── routers/
│       ├── errors.py         # エラー一覧・統計
│       ├── versions.py       # バージョン一覧
│       ├── reviews.py        # レビュー保存・取得
│       ├── ingest.py         # CSV取込
│       └── export.py         # CSVエクスポート
├── frontend/                 # React + TypeScript（別途作成）
└── data/
    ├── incoming/             # ← CSVをここに置く
    ├── processed/            # 取込済みCSV
    ├── error/                # 取込失敗CSV
    └── errorscope.duckdb     # DBファイル（自動生成）
```

---

## セットアップ

### 1. バックエンド

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# APIサーバー起動
uvicorn main:app --reload --port 8000
```

### 2. ファイル監視（別ターミナル）

```bash
cd backend
source .venv/bin/activate

# data/incoming/ を監視して自動取込
python watcher.py
```

### 3. CSVを取込む

```bash
# data/incoming/ にCSVを配置するだけで自動取込
cp /path/to/v2.1.0_errors.csv data/incoming/

# または APIを直接呼ぶ
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"filepath": "/absolute/path/to/v2.1.0_errors.csv"}'
```

---

## APIエンドポイント一覧

| Method | Path | 説明 |
|--------|------|------|
| GET | `/health` | ヘルスチェック・DuckDBバージョン確認 |
| GET | `/versions` | バージョン一覧（`?project=MyApp`） |
| GET | `/errors` | エラー一覧（ページネーション・フィルタ付き） |
| GET | `/errors/stats` | 統計サマリー（Total/New/Recurring/Reviewed） |
| GET | `/reviews/{err_key}` | レビュー取得 |
| PUT | `/reviews/{err_key}` | レビュー保存（comment・result） |
| POST | `/ingest` | CSV取込 |
| DELETE | `/ingest/{project}/{version}` | バージョンデータ削除（再取込用） |
| GET | `/export/{version}` | CSV エクスポート |

Swagger UI: http://localhost:8000/docs

---

## エラー一覧APIの主なパラメータ

```
GET /errors?version=v2.0.0&page=1&limit=50&q=タイムアウト&filter=recurring
```

| パラメータ | 説明 | 例 |
|---|---|---|
| `version` | 対象バージョン（必須） | `v2.0.0` |
| `project` | プロジェクト名フィルタ | `MyApp` |
| `q` | キーワード検索 | `タイムアウト` |
| `filter` | `all` / `new` / `recurring` / `unreviewed` | `recurring` |
| `page` | ページ番号（1始まり） | `1` |
| `limit` | 1ページあたりの件数（最大200） | `50` |

---

## DuckDB の利点（このプロジェクトにおいて）

### CSV直接クエリ
```python
# 取込パイプライン不要
conn.execute("""
    INSERT INTO error_logs
    SELECT *, md5(project || err_code || err_summary) AS err_key
    FROM read_csv('/data/incoming/v2.1.0.csv', header=true)
""")
```

### バージョン比較を1クエリで
```sql
-- err_keyごとに全バージョンの出現履歴をリスト化
SELECT
    err_key,
    err_summary,
    list(DISTINCT version ORDER BY version) AS appeared_in
FROM error_logs
GROUP BY err_key, err_summary
```

### 統計を FILTER 句でまとめて集計
```sql
SELECT
    COUNT(*)                                        AS total,
    COUNT(*) FILTER (WHERE len(appeared_in) = 1)   AS new_count,
    COUNT(*) FILTER (WHERE len(appeared_in) > 1)   AS recurring,
    COUNT(*) FILTER (WHERE result IS NOT NULL)      AS reviewed
FROM ...
```

---

## 注意事項

- **同時書き込み非対応**: 複数プロセスからの同時書き込みはDuckDBの制約によりエラーになります
- **シングルライター前提**: APIサーバーは必ず1プロセスで起動してください（`--workers 1`）
- DBファイルのバックアップは `errorscope.duckdb` をコピーするだけで完了します
