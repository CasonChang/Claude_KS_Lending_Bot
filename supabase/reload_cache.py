"""通知 PostgREST 重載 schema 快取（建表/建函式後 API 404 時用）。
用法：python supabase/reload_cache.py <db密碼>
"""
import sys

import psycopg2

password = sys.argv[1]
conn = psycopg2.connect(host="db.djcebqribkmtrhkoytaq.supabase.co", port=5432,
                        dbname="postgres", user="postgres",
                        password=password, connect_timeout=15)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("NOTIFY pgrst, 'reload schema'")
    cur.execute("select proname from pg_proc where proname = 'dashboard_data'")
    print("function exists:", cur.fetchone())
conn.close()
print("reload sent")
