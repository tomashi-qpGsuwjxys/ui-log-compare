# ErrorScope — DuckDB版 アーキテクチャ & シーケンス図

> **前提**: 同時書き込みなし（シングルライター）、開発チーム内部ツール

---

## 1. システムアーキテクチャ全体図

```mermaid
graph TB
    subgraph INPUT["📂 入力層"]
        CSV["CSVファイル群<br/>（100KB × 最大1000バージョン）<br/>/data/incoming/"]
        PROCESSED["処理済みCSV<br/>/data/processed/"]
    end

    subgraph INGEST["⚙️ 取込パイプライン（Python）"]
        WATCH["ファイル監視<br/>watchdog"]
        READER["DuckDB read_csv()<br/>取込パイプライン不要・直接クエリ"]
        VALIDATOR["バリデーター<br/>スキーマ・重複チェック"]
    end

    subgraph DB["🦆 データ層（DuckDB）"]
        DUCKFILE["errorscope.duckdb<br/>単一ファイル"]
        TBL_LOGS["error_logs テーブル<br/>列指向ストレージ"]
        TBL_REVIEWS["reviews テーブル<br/>レビュー・判定結果"]
        TBL_VERSIONS["versions テーブル<br/>バージョンメタ情報"]
        TBL_RAW["raw_csv ビュー<br/>read_csv() ラッパー<br/>（取込前の即時クエリ用）"]
    end

    subgraph API["🔌 APIサーバー（FastAPI / Python）"]
        EP_ERRORS["GET /errors<br/>ページネーション・フィルタ"]
        EP_DIFF["GET /errors/diff<br/>バージョン出現履歴"]
        EP_VERSIONS["GET /versions<br/>バージョン一覧・統計"]
        EP_REVIEW["PUT /reviews/{err_key}<br/>レビュー保存"]
        EP_INGEST["POST /ingest<br/>CSV取込トリガー"]
        EP_EXPORT["GET /export<br/>CSVエクスポート"]
    end

    subgraph FRONT["🖥️ フロントエンド（React + TypeScript）"]
        SIDEBAR["サイドバー<br/>バージョン選択"]
        STATS["統計ストリップ<br/>Total / New / Recurring / Reviewed"]
        TABLE["仮想スクロールテーブル<br/>TanStack Virtual"]
        DRAWER["詳細ドロワー<br/>バージョン履歴 + レビュー入力"]
    end

    subgraph INFRA["📦 シンプル構成（Docker不要）"]
        PROC_API["uvicorn api:app<br/>ポート 8000"]
        PROC_FRONT["vite dev / nginx<br/>ポート 3000"]
        PROC_WATCH["python watcher.py<br/>バックグラウンドプロセス"]
    end

    CSV --> WATCH
    WATCH --> READER
    READER --> VALIDATOR
    VALIDATOR --> TBL_LOGS
    VALIDATOR --> TBL_VERSIONS
    VALIDATOR --> PROCESSED

    DUCKFILE --- TBL_LOGS
    DUCKFILE --- TBL_REVIEWS
    DUCKFILE --- TBL_VERSIONS
    DUCKFILE --- TBL_RAW

    TBL_LOGS --> EP_ERRORS
    TBL_LOGS --> EP_DIFF
    TBL_VERSIONS --> EP_VERSIONS
    TBL_REVIEWS --> EP_REVIEW
    TBL_LOGS --> EP_EXPORT
    TBL_REVIEWS --> EP_EXPORT
    CSV --> EP_INGEST

    EP_ERRORS --> TABLE
    EP_DIFF --> DRAWER
    EP_VERSIONS --> SIDEBAR
    EP_VERSIONS --> STATS
    EP_REVIEW --> DRAWER
    EP_EXPORT --> FRONT

    PROC_API -.- EP_ERRORS
    PROC_FRONT -.- SIDEBAR
    PROC_WATCH -.- WATCH
```

---

## 2. DBスキーマ ER図

```mermaid
erDiagram
    versions {
        VARCHAR  version        PK  "例: v2.0.0"
        VARCHAR  project        PK  "プロジェクト名"
        TIMESTAMP imported_at      "取込日時"
        INTEGER  row_count         "CSVの行数"
        VARCHAR  file_path         "元CSVパス"
    }

    error_logs {
        BIGINT   id             PK
        VARCHAR  project
        VARCHAR  version
        VARCHAR  process_name
        VARCHAR  category
        VARCHAR  toolname
        VARCHAR  logpath
        VARCHAR  err_code
        VARCHAR  err_summary
        VARCHAR  err_key           "MD5(project||err_code||err_summary)"
    }

    reviews {
        VARCHAR   err_key       PK  "error_logsのerr_keyと対応"
        VARCHAR   project
        TEXT      comment
        VARCHAR   result            "OK / NG / WIP / NEW"
        TIMESTAMP updated_at
    }

    versions   ||--o{ error_logs : "version + project"
    error_logs }o--o| reviews    : "err_key"
```

---

## 3. CSV取込シーケンス

```mermaid
sequenceDiagram
    actor OPS  as 運用担当者
    participant FS   as ファイルシステム<br/>/data/incoming/
    participant WCH  as watcher.py<br/>(watchdog)
    participant API  as FastAPI<br/>POST /ingest
    participant DUCK as DuckDB<br/>(errorscope.duckdb)

    OPS  ->> FS   : CSVファイルを配置<br/>例: v2.1.0_errors.csv

    FS   -->> WCH : ファイル作成イベント検知
    WCH  ->> API  : POST /ingest<br/>{ filepath: "/data/incoming/v2.1.0_errors.csv" }

    activate API

    API  ->> DUCK : バージョン重複チェック
    Note over API,DUCK: SELECT COUNT(*) FROM versions<br/>WHERE version = 'v2.1.0' AND project = 'MyApp'
    DUCK -->> API : 0件 → 取込OK

    API  ->> DUCK : read_csv() で直接スキーマ確認
    Note over API,DUCK: DESCRIBE SELECT * FROM<br/>read_csv('/data/incoming/v2.1.0_errors.csv')
    DUCK -->> API : カラム情報

    API  ->> DUCK : error_logs へ INSERT
    Note over API,DUCK: INSERT INTO error_logs<br/>SELECT *, md5(project||err_code||err_summary) AS err_key<br/>FROM read_csv('/data/incoming/v2.1.0_errors.csv')
    DUCK -->> API : INSERT完了（行数返却）

    API  ->> DUCK : versions へ upsert
    Note over API,DUCK: INSERT OR REPLACE INTO versions<br/>VALUES (version, project, now(), row_count, filepath)
    DUCK -->> API : upsert完了

    deactivate API

    API  -->> WCH : { success: true, rows: 487 }
    WCH  ->> FS   : /data/processed/ へ移動
    WCH  -->> OPS : ログ出力「v2.1.0: 487行 取込完了」
```

---

## 4. エラー一覧表示シーケンス

```mermaid
sequenceDiagram
    actor USER  as 開発者
    participant UI   as React
    participant VIRT as TanStack Virtual
    participant API  as FastAPI
    participant DUCK as DuckDB

    USER ->> UI   : ダッシュボード初期表示

    UI   ->> API  : GET /versions?project=MyApp
    API  ->> DUCK : SELECT version, project, row_count,<br/>imported_at FROM versions<br/>ORDER BY version
    DUCK -->> API : versions[]（最大1000件）
    API  -->> UI  : versions[]

    UI   ->> UI   : 最新バージョンを自動選択（v2.1.0）

    par 並列リクエスト
        UI ->> API : GET /errors?version=v2.1.0&page=1&limit=50
        and
        UI ->> API : GET /errors/stats?version=v2.1.0
    end

    API  ->> DUCK : エラー一覧 + 出現バージョン履歴
    Note over API,DUCK: SELECT<br/>  e.*,<br/>  r.comment, r.result,<br/>  list(e2.version ORDER BY e2.version)<br/>    AS appeared_in<br/>FROM error_logs e<br/>LEFT JOIN reviews r USING (err_key)<br/>LEFT JOIN error_logs e2 USING (err_key)<br/>WHERE e.version = 'v2.1.0'<br/>GROUP BY e.id, r.comment, r.result<br/>LIMIT 50 OFFSET 0
    DUCK -->> API : errors[]（出現履歴付き）

    API  ->> DUCK : 統計集計
    Note over API,DUCK: SELECT<br/>  COUNT(*) AS total,<br/>  COUNT(*) FILTER(WHERE appeared_in = [version])<br/>    AS new_count,<br/>  COUNT(*) FILTER(WHERE len(appeared_in) > 1)<br/>    AS recurring,<br/>  COUNT(r.result) AS reviewed<br/>FROM ...
    DUCK -->> API : stats

    API  -->> UI  : errors[] + stats
    UI   ->> VIRT : 50件を仮想スクロールで描画
    VIRT ->> UI   : 画面内の行のみDOM生成（約15〜20行）

    USER ->> UI   : スクロール
    VIRT ->> VIRT : 表示範囲を再計算・DOM更新
    UI   ->> API  : GET /errors?version=v2.1.0&page=2&limit=50
    API  ->> DUCK : LIMIT 50 OFFSET 50
    DUCK -->> API : errors[]
    API  -->> UI  : 追加データ
```

---

## 5. フィルタ・検索シーケンス

```mermaid
sequenceDiagram
    actor USER  as 開発者
    participant UI   as React
    participant API  as FastAPI
    participant DUCK as DuckDB

    USER ->> UI   : 検索キーワード入力「タイムアウト」<br/>フィルタ「Recurring」選択

    Note over UI  : デバウンス処理（300ms待機）

    UI   ->> API  : GET /errors?version=v2.1.0<br/>&q=タイムアウト&filter=recurring<br/>&page=1&limit=50

    activate API
    API  ->> DUCK : 動的WHERE句でクエリ生成
    Note over API,DUCK: WHERE e.version = 'v2.1.0'<br/>AND (<br/>  e.err_code ILIKE '%タイムアウト%'<br/>  OR e.err_summary ILIKE '%タイムアウト%'<br/>  OR e.process_name ILIKE '%タイムアウト%'<br/>)<br/>-- filter=recurring:<br/>HAVING len(list(e2.version)) > 1
    DUCK -->> API : フィルタ済み結果
    deactivate API

    API  -->> UI  : { data: errors[], total: 3 }
    UI   ->> UI   : テーブル再描画・スクロールリセット
```

---

## 6. レビュー保存シーケンス

```mermaid
sequenceDiagram
    actor DEV  as 開発者
    participant UI   as React
    participant API  as FastAPI
    participant DUCK as DuckDB

    DEV  ->> UI   : 「Detail →」ボタンをクリック

    UI   ->> API  : GET /reviews/{err_key}
    API  ->> DUCK : SELECT * FROM reviews<br/>WHERE err_key = ?
    DUCK -->> API : 既存レビュー or null
    API  -->> UI  : review
    UI   ->> UI   : ドロワー表示（既存コメント・判定を反映）

    DEV  ->> UI   : コメント入力・判定選択（OK）
    DEV  ->> UI   : 「Save Review」クリック

    UI   ->> API  : PUT /reviews/{err_key}<br/>{ comment: "既知の問題。v2.2.0で修正予定",<br/>  result: "OK" }

    activate API
    Note over API  : シングルライター前提<br/>排他制御不要
    API  ->> DUCK : INSERT OR REPLACE INTO reviews<br/>VALUES (err_key, project, comment,<br/>        result, now())
    DUCK -->> API : upsert完了
    deactivate API

    API  -->> UI  : { success: true, updated_at: "..." }
    UI   ->> UI   : テーブル行のRESULT列をインプレース更新
    UI   ->> UI   : 統計「Reviewed」カウント更新
    UI   ->> UI   : トースト「Review saved」表示
```

---

## 7. プロジェクト構成図

```mermaid
graph TD
    subgraph ROOT["errorscope/"]
        subgraph BACK["backend/"]
            MAIN["main.py<br/>FastAPI エントリポイント"]
            subgraph ROUTERS["routers/"]
                R_ERR["errors.py"]
                R_VER["versions.py"]
                R_REV["reviews.py"]
                R_ING["ingest.py"]
                R_EXP["export.py"]
            end
            subgraph CORE["core/"]
                DB["database.py<br/>DuckDB接続管理（シングルトン）"]
                SCHEMA["schema.py<br/>テーブル定義・初期化SQL"]
                MODELS["models.py<br/>Pydanticスキーマ"]
            end
            WATCHER["watcher.py<br/>watchdog ファイル監視"]
            REQ["requirements.txt<br/>fastapi / duckdb / watchdog / pandas"]
        end

        subgraph FRONT["frontend/"]
            subgraph SRC["src/"]
                subgraph COMP["components/"]
                    C_SIDE["Sidebar.tsx"]
                    C_STATS["StatsStrip.tsx"]
                    C_TABLE["ErrorTable.tsx<br/>+ TanStack Virtual"]
                    C_DRAWER["DetailDrawer.tsx"]
                    C_FILTER["FilterToolbar.tsx"]
                end
                subgraph HOOKS["hooks/"]
                    H_ERR["useErrors.ts<br/>ページネーション・無限スクロール"]
                    H_VER["useVersions.ts"]
                    H_REV["useReview.ts"]
                end
                subgraph API_CLI["api/"]
                    A_CLIENT["client.ts<br/>axios インスタンス"]
                    A_ERRORS["errors.ts"]
                    A_REVIEWS["reviews.ts"]
                end
            end
            PKG["package.json<br/>react / tanstack-virtual<br/>tanstack-query / vite"]
        end

        subgraph DATA["data/"]
            INCOMING["/incoming/<br/>（CSV投入口）"]
            PROC["/processed/<br/>（取込済みCSV）"]
            DUCKDB["errorscope.duckdb<br/>🦆 単一DBファイル"]
        end

        ENV[".env<br/>DATA_DIR / DB_PATH / API_URL"]
        README["README.md"]
    end
```

---

## 8. PostgreSQL vs DuckDB 構成比較

```mermaid
graph LR
    subgraph PG_STACK["PostgreSQL構成（旧案）"]
        direction TB
        PG_CSV["CSV"] --> PG_PIPE["取込パイプライン<br/>pandas"]
        PG_PIPE --> PG_DB["PostgreSQL<br/>（Dockerが必要）"]
        PG_DB --> PG_API["FastAPI"]
        PG_API --> PG_UI["React"]
    end

    subgraph DK_STACK["DuckDB構成（今回）"]
        direction TB
        DK_CSV["CSV"] --> DK_DB["DuckDB<br/>read_csv()で直接取込<br/>（Dockerなし・1ファイル）"]
        DK_DB --> DK_API["FastAPI"]
        DK_API --> DK_UI["React"]
    end

    PG_STACK -->|"シンプル化"| DK_STACK
```
