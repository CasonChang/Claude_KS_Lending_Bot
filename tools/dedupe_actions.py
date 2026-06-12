"""用 PostgREST 清掉 actions_log 重複列（多實例事故善後）。
同 action + 相同 detail 只留最早一筆。
用法：python tools/dedupe_actions.py
"""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lendbot.config import load_config

cfg = load_config()
base = f"{cfg.env.supabase_url}/rest/v1/actions_log"
headers = {"apikey": cfg.env.supabase_key,
           "Authorization": f"Bearer {cfg.env.supabase_key}"}

rows = requests.get(base, params={"order": "id.asc", "limit": 1000},
                    headers=headers, timeout=15).json()
seen: dict[str, int] = {}
dupes: list[int] = []
for r in rows:
    key = r["action"] + "|" + json.dumps(r.get("detail"), sort_keys=True)
    if key in seen:
        dupes.append(r["id"])
    else:
        seen[key] = r["id"]

print(f"共 {len(rows)} 列，發現 {len(dupes)} 列重複")
if dupes:
    for i in range(0, len(dupes), 50):
        chunk = ",".join(str(x) for x in dupes[i:i + 50])
        resp = requests.delete(base, params={"id": f"in.({chunk})"},
                               headers=headers, timeout=15)
        print(f"刪除 {min(i + 50, len(dupes))}/{len(dupes)}：HTTP {resp.status_code}")
print("完成")
