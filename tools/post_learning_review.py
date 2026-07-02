"""把一份每日學習檢討 markdown upsert 到 Supabase learning_reviews 表。

用法：
    python tools/post_learning_review.py reviews/learning/2026-07-05.md

需要環境變數 SUPABASE_SERVICE_KEY（伺服器端 service_role key）。
SUPABASE_URL 可省略，預設用 web/config.js 裡的專案 URL。

markdown 檔需含 YAML front matter：
    ---
    date: "2026-07-05"          # 檢討覆蓋的 Bitfinex 結算日（UTC 日）
    title: "一句話重點"
    metrics: { ... }            # 選填
    ---
    # markdown 全文...
"""
import os
import sys

import requests
import yaml

DEFAULT_URL = "https://djcebqribkmtrhkoytaq.supabase.co"


def parse_review(path: str) -> dict:
    text = open(path, encoding="utf-8").read()
    if not text.startswith("---"):
        raise SystemExit("檔案開頭要有 YAML front matter（--- ... ---）")
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm) or {}
    if not meta.get("date"):
        raise SystemExit("front matter 缺少 date")
    return {
        "date": str(meta["date"]),
        "title": meta.get("title"),
        "metrics": meta.get("metrics"),
        "body_md": body.strip(),
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("用法：python tools/post_learning_review.py <reviews/learning/YYYY-MM-DD.md>")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        raise SystemExit("缺少環境變數 SUPABASE_SERVICE_KEY")
    url = os.environ.get("SUPABASE_URL", DEFAULT_URL).rstrip("/")
    row = parse_review(sys.argv[1])
    r = requests.post(
        f"{url}/rest/v1/learning_reviews",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        params={"on_conflict": "date"},
        json=row,
        timeout=15,
    )
    if r.status_code >= 300:
        raise SystemExit(f"upsert 失敗 {r.status_code}: {r.text[:300]}")
    print(f"✅ 已上傳每日學習檢討：{row['date']}")


if __name__ == "__main__":
    main()
