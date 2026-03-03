"""
watcher.py
/data/incoming/ を監視して新CSVを自動取込する
バックグラウンドプロセスとして実行: python watcher.py
"""
import os
import time
import shutil
import requests
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

INCOMING_DIR  = Path(os.getenv("INCOMING_DIR",  "./data/incoming"))
PROCESSED_DIR = Path(os.getenv("PROCESSED_DIR", "./data/processed"))
ERROR_DIR     = Path(os.getenv("ERROR_DIR",     "./data/error"))
API_BASE      = os.getenv("API_BASE", "http://localhost:8000")

# ディレクトリ作成
for d in [INCOMING_DIR, PROCESSED_DIR, ERROR_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class CsvHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".csv":
            return

        # ファイル書き込み完了を待つ（大きいファイル対策）
        time.sleep(0.5)
        self._ingest(path)

    def _ingest(self, path: Path):
        print(f"📂 新ファイル検知: {path.name}")
        try:
            resp = requests.post(
                f"{API_BASE}/ingest",
                json={"filepath": str(path.resolve())},
                timeout=120,
            )
            data = resp.json()

            if data.get("success"):
                # 処理済みディレクトリへ移動
                dest = PROCESSED_DIR / path.name
                shutil.move(str(path), dest)
                print(f"✅ 取込完了: {data['project']} / {data['version']} "
                      f"({data['rows']}件) → {dest}")
            else:
                # エラーディレクトリへ移動
                dest = ERROR_DIR / path.name
                shutil.move(str(path), dest)
                print(f"⚠️  取込スキップ: {data.get('message')} → {dest}")

        except Exception as e:
            print(f"❌ 取込エラー: {path.name}: {e}")
            dest = ERROR_DIR / path.name
            shutil.move(str(path), dest)


if __name__ == "__main__":
    print(f"👀 監視開始: {INCOMING_DIR.resolve()}")
    handler  = CsvHandler()
    observer = Observer()
    observer.schedule(handler, str(INCOMING_DIR), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    print("🛑 監視停止")
