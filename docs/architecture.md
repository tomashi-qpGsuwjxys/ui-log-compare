# ErrorScope — アーキテクチャ & シーケンス図

---

## 1. システムアーキテクチャ全体図

```mermaid
graph TB
    subgraph INPUT["📂 入力層"]
        CSV["CSVファイル群<br/>（100KB × 最大1000バージョン）"]
        WATCH["ファイル監視<br/>watchdog"]
    end

    subgraph INGEST["⚙️ 取込パイプライン（Python）"]
        PARSER["CSVパーサー<br/>pandas"]
        VALIDATOR["バリデーター<br/>スキーマチェック・重複排除"]
        NORMALIZER["ノーマライザー<br/>バージョン正規化・型変換"]
    end

    subgraph DB["🗄️ データ層（PostgreSQL）"]
        TBL_LOGS["error_logs テーブル<br/>project / version / err_code<br/>process_name / err_summary..."]
        TBL_REVIEWS["reviews テーブル<br/>err_key / comment / result<br/>updated_at / updated_by"]
        TBL_VERSIONS["versions テーブル<br/>version / project<br/>imported_at / file_count"]
        IDX["インデックス<br/>version / err_code / project"]
    end

    subgraph API["🔌 APIサーバー（FastAPI / Python）"]
        EP_ERRORS["GET /errors<br/>ページネーション・フィルタ"]
        EP_DIFF["GET /errors/diff<br/>バージョン比較・出現履歴"]
        EP_VERSIONS["GET /versions<br/>バージョン一覧・統計"]
        EP_REVIEW["PUT /reviews/{err_key}<br/>レビュー保存"]
        EP_EXPORT["GET /export<br/>CSVエクスポート"]
    end

    subgraph FRONT["🖥️ フロントエンド（React + TypeScript）"]
        SIDEBAR["サイドバー<br/>バージョン選択"]
        STATS["統計ストリップ<br/>Total / New / Recurring / Reviewed"]
        TABLE["仮想スクロールテーブル<br/>TanStack Virtual<br/>（表示行のみDOM描画）"]
        DRAWER["詳細ドロワー<br/>バージョン履歴 + レビュー入力"]
        FILTER["フィルタ・検索<br/>サーバーサイド処理"]
    end

    subgraph INFRA["🐳 インフラ（Docker Compose）"]
        CONTAINER_FRONT["frontend:3000"]
        CONTAINER_API["api:8000"]
        CONTAINER_DB["postgres:5432"]
        CONTAINER_WATCH["watcher"]
    end

    CSV --> WATCH
    WATCH --> PARSER
    PARSER --> VALIDATOR
    VALIDATOR --> NORMALIZER
    NORMALIZER --> TBL_LOGS
    NORMALIZER --> TBL_VERSIONS

    TBL_LOGS --> IDX
    TBL_REVIEWS --> IDX

    TBL_LOGS --> EP_ERRORS
    TBL_LOGS --> EP_DIFF
    TBL_VERSIONS --> EP_VERSIONS
    TBL_REVIEWS --> EP_REVIEW
    TBL_LOGS --> EP_EXPORT
    TBL_REVIEWS --> EP_EXPORT

    EP_ERRORS --> FILTER
    EP_DIFF --> TABLE
    EP_VERSIONS --> SIDEBAR
    EP_VERSIONS --> STATS
    EP_REVIEW --> DRAWER
    EP_ERRORS --> TABLE

    SIDEBAR --> STATS
    STATS --> TABLE
    TABLE --> DRAWER
    FILTER --> TABLE

    CONTAINER_FRONT -.->|HTTP| CONTAINER_API
    CONTAINER_API -.->|SQL| CONTAINER_DB
    CONTAINER_WATCH -.->|ファイル検知| CONTAINER_API
```

---

## 2. DBスキーマ ER図

```mermaid
erDiagram
    versions {
        serial   id           PK
        varchar  project
        varchar  version
        timestamp imported_at
        int      row_count
        varchar  file_path
    }

    error_logs {
        serial   id           PK
        int      version_id   FK
        varchar  project
        varchar  version
        varchar  process_name
        varchar  category
        varchar  toolname
        text     logpath
        varchar  err_code
        text     err_summary
        varchar  err_key      "project::err_code::err_summaryのハッシュ"
    }

    reviews {
        serial    id          PK
        varchar   err_key     FK
        varchar   project
        text      comment
        varchar   result      "OK / NG / WIP / NEW"
        varchar   updated_by
        timestamp updated_at
    }

    versions   ||--o{ error_logs  : "1 version has many logs"
    error_logs }o--o| reviews     : "err_key links review"
```

---

## 3. CSV取込シーケンス

```mermaid
sequenceDiagram
    actor OPS as 運用担当者
    participant FS  as ファイルシステム
    participant WCH as Watcherサービス
    participant ING as 取込パイプライン<br/>(pandas)
    participant DB  as PostgreSQL

    OPS  ->> FS  : CSVファイルを所定ディレクトリに配置<br/>例: /data/incoming/v2.1.0.csv
    FS   -->> WCH: ファイル作成イベント検知 (watchdog)
    WCH  ->> ING : ingest_csv(filepath) 呼び出し

    activate ING
    ING  ->> ING : pandas.read_csv() でパース
    ING  ->> ING : スキーマバリデーション<br/>（必須列の存在確認・型チェック）
    ING  ->> DB  : versions テーブルに upsert<br/>（同バージョンの二重取込防止）
    DB   -->> ING: version_id 返却

    ING  ->> ING : err_key 生成<br/>（project::err_code::err_summaryのハッシュ）
    ING  ->> DB  : error_logs テーブルに bulk insert<br/>（バッチサイズ: 1000行単位）
    DB   -->> ING: INSERT完了
    ING  ->> DB  : インデックス更新 (ANALYZE)
    deactivate ING

    ING  -->> WCH: 取込完了通知
    WCH  ->> FS  : 処理済みディレクトリへファイル移動<br/>/data/processed/v2.1.0.csv
    WCH  -->> OPS: 取込完了ログ出力
```

---

## 4. エラー一覧表示シーケンス

```mermaid
sequenceDiagram
    actor USER  as 開発者
    participant UI   as React フロントエンド
    participant VIRT as TanStack Virtual<br/>(仮想スクロール)
    participant API  as FastAPI
    participant DB   as PostgreSQL

    USER ->> UI   : ダッシュボード初期表示

    UI   ->> API  : GET /versions?project=MyApp
    API  ->> DB   : SELECT * FROM versions ORDER BY version
    DB   -->> API : バージョン一覧（1000件）
    API  -->> UI  : versions[]

    UI   ->> UI   : 最新バージョンを自動選択

    UI   ->> API  : GET /errors?version=v2.0.0&page=1&limit=50
    API  ->> DB   : SELECT + バージョン出現履歴JOIN<br/>LIMIT 50 OFFSET 0
    DB   -->> API : error_logs[] + 出現バージョン配列
    API  -->> UI  : { data: errors[], total: 480, page: 1 }

    UI   ->> API  : GET /errors/stats?version=v2.0.0
    API  ->> DB   : 集計クエリ（Total/New/Recurring/Reviewed）
    DB   -->> API : { total: 480, new: 12, recurring: 468, reviewed: 200 }
    API  -->> UI  : stats

    UI   ->> VIRT : 50件を仮想スクロールで描画
    VIRT ->> UI   : 画面内の行のみDOM生成（約15〜20行）

    USER ->> UI   : スクロール操作
    VIRT ->> VIRT : 表示範囲の行を再計算
    VIRT ->> UI   : 新しい表示行のみDOMを更新

    USER ->> UI   : 次ページ付近までスクロール
    UI   ->> API  : GET /errors?version=v2.0.0&page=2&limit=50
    API  ->> DB   : LIMIT 50 OFFSET 50
    DB   -->> API : error_logs[]
    API  -->> UI  : 追加データ
    UI   ->> VIRT : データ追加・スクロール継続
```

---

## 5. フィルタ・検索シーケンス

```mermaid
sequenceDiagram
    actor USER  as 開発者
    participant UI  as React フロントエンド
    participant API as FastAPI
    participant DB  as PostgreSQL

    USER ->> UI  : 検索キーワード入力 or フィルタ選択

    Note over UI: デバウンス処理 (300ms待機)

    UI   ->> API : GET /errors?version=v2.0.0<br/>&q=タイムアウト&filter=recurring<br/>&page=1&limit=50
    activate API
    API  ->> DB  : SELECT e.*, array_agg(e2.version) as appeared_in<br/>FROM error_logs e<br/>LEFT JOIN error_logs e2 ON e.err_key = e2.err_key<br/>WHERE e.version = 'v2.0.0'<br/>AND (e.err_code ILIKE '%タイムアウト%'<br/>  OR e.err_summary ILIKE '%タイムアウト%')<br/>GROUP BY e.id<br/>HAVING count(DISTINCT e2.version) > 1<br/>LIMIT 50
    DB   -->> API: フィルタ済み結果
    deactivate API
    API  -->> UI : { data: errors[], total: 8 }

    UI   ->> UI  : テーブルを再描画（仮想スクロールリセット）
```

---

## 6. レビュー保存シーケンス

```mermaid
sequenceDiagram
    actor DEV   as 開発者
    participant UI  as React フロントエンド
    participant API as FastAPI
    participant DB  as PostgreSQL

    DEV  ->> UI  : 詳細ドロワーを開く (Detail → ボタン)
    UI   ->> API : GET /reviews/{err_key}
    API  ->> DB  : SELECT * FROM reviews WHERE err_key = ?
    DB   -->> API: 既存レビュー（なければ null）
    API  -->> UI : review | null
    UI   ->> UI  : ドロワーにコメント・判定結果を表示

    DEV  ->> UI  : コメント入力・判定結果（OK/NG/WIP/NEW）を選択
    DEV  ->> UI  : 「Save Review」ボタンをクリック

    UI   ->> API : PUT /reviews/{err_key}<br/>{ comment: "...", result: "OK", updated_by: "dev@example.com" }
    activate API
    API  ->> DB  : INSERT INTO reviews ... ON CONFLICT (err_key)<br/>DO UPDATE SET comment=?, result=?, updated_at=NOW()
    DB   -->> API: upsert 完了
    deactivate API
    API  -->> UI : { success: true, updated_at: "2026-03-03T..." }

    UI   ->> UI  : テーブル行のRESULT列をインプレース更新
    UI   ->> UI  : 統計ストリップの "Reviewed" カウントを更新
    UI   ->> UI  : トースト通知「Review saved」表示
```

---

## 7. デプロイ構成図（Docker Compose）

```mermaid
graph LR
    subgraph HOST["ホストマシン / サーバー"]
        subgraph COMPOSE["docker compose"]
            FE["frontend<br/>React + Vite<br/>:3000"]
            BE["api<br/>FastAPI + uvicorn<br/>:8000"]
            PG["postgres<br/>PostgreSQL 16<br/>:5432"]
            WC["watcher<br/>Python watchdog"]
        end

        VOL_DATA["/data/incoming<br/>/data/processed<br/>（CSVマウント）"]
        VOL_DB["/var/lib/postgresql<br/>（DBマウント）"]
    end

    BROWSER["ブラウザ"] -->|":3000"| FE
    FE -->|"API呼び出し :8000"| BE
    BE -->|"SQL :5432"| PG
    WC -->|"REST POST /ingest"| BE
    PG --- VOL_DB
    WC --- VOL_DATA
    BE --- VOL_DATA
```
