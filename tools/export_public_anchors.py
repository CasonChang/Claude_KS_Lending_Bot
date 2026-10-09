"""匯出只含市場錨點的靜態備援。密碼由環境注入，不寫入檔案。

即時來源應安裝 migration 015；此工具只在尚未安裝時提供標明日期的歷史圖。
"""
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def public_rows(rows):
    result = []
    for row in rows:
        rate = row.get("anchor_apy")
        if (row.get("symbol") not in {"fUSD", "fUST"}
                or not isinstance(rate, (int, float)) or isinstance(rate, bool)
                or not math.isfinite(rate) or rate < 0):
            continue
        try:
            datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        result.append({key: row[key] for key in ("ts", "symbol", "anchor_apy")})
    return sorted(result, key=lambda row: (row["ts"], row["symbol"]))


def main():
    cfg = (ROOT / "web/config.js").read_text()
    url = re.search(r'SUPABASE_URL:\s*"([^"]+)"', cfg).group(1)
    anon = re.search(r'SUPABASE_ANON_KEY:\s*"([^"]+)"', cfg).group(1)
    token = os.environ.get("Dashboard_Password") or os.environ.get("DASHBOARD_PASSWORD")
    if not token:
        raise SystemExit("請在環境設定 Dashboard_Password 或 DASHBOARD_PASSWORD")
    response = requests.post(f"{url}/rest/v1/rpc/dashboard_data",
                             headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
                             json={"p_token": token}, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise SystemExit("Dashboard 密碼未通過驗證")
    rows = public_rows(data.get("snapshots") or [])
    output = ROOT / "web/public-anchors.json"
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps({"exported_at": datetime.now(timezone.utc).isoformat(),
                               "snapshots": rows}, separators=(",", ":")) + "\n")
    tmp.replace(output)
    print(f"已匯出 {len(rows)} 筆公開市場錨點（僅時間／幣別／年化）")


if __name__ == "__main__":
    main()
