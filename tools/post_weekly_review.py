"""把一份每週檢討 markdown upsert 到 Supabase weekly_reviews 表，網頁就讀得到。

用法：
    python tools/post_weekly_review.py reviews/2026-06-13.md

需要環境變數 SUPABASE_SERVICE_KEY（伺服器端 service_role key）。
SUPABASE_URL 可省略，預設用 web/config.js 裡的專案 URL。

markdown 檔需含 YAML front matter：
    ---
    week: "2026-06-13"
    period: "06/13(六)–06/19(五)"
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
    for k in ("week", "period"):
        if not meta.get(k):
            raise SystemExit(f"front matter 缺少 {k}")
    return {
        "week": str(meta["week"]),
        "period": str(meta["period"]),
        "title": meta.get("title"),
        "metrics": meta.get("metrics"),
        "body_md": body.strip(),
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("用法：python tools/post_weekly_review.py <reviews/YYYY-MM-DD.md>")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        raise SystemExit("缺少環境變數 SUPABASE_SERVICE_KEY")
    url = os.environ.get("SUPABASE_URL", DEFAULT_URL).rstrip("/")
    row = parse_review(sys.argv[1])
    r = requests.post(
        f"{url}/rest/v1/weekly_reviews",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        params={"on_conflict": "week"},
        json=row,
        timeout=15,
    )
    if r.status_code >= 300:
        raise SystemExit(f"upsert 失敗 {r.status_code}: {r.text[:300]}")
    print(f"✅ 已上傳每週檢討：{row['week']}（{row['period']}）")


if __name__ == "__main__":
    main()
