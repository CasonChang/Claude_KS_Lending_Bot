"""把 schema.sql 套用到 Supabase（直連 Postgres）。
用法：python supabase/apply_schema.py <db密碼>
"""
import sys
from pathlib import Path

import psycopg2

HOST = "db.djcebqribkmtrhkoytaq.supabase.co"
SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

password = sys.argv[1] if len(sys.argv) > 1 else ""
if not password:
    print("用法：python supabase/apply_schema.py <db密碼>")
    sys.exit(1)

try:
    conn = psycopg2.connect(host=HOST, port=5432, dbname="postgres",
                            user="postgres", password=password,
                            connect_timeout=15)
except Exception as e:
    print(f"❌ 連線失敗：{e}")
    sys.exit(2)

conn.autocommit = True
with conn.cursor() as cur:
    cur.execute(SQL)
    cur.execute("select count(*) from app_settings")
    print("✅ schema 套用成功，app_settings 列數：", cur.fetchone()[0])
conn.close()
