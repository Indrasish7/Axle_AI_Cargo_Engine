import sqlite3
import json

conn = sqlite3.connect("axle_ai.db")
cursor = conn.cursor()

print("=== Tables ===")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]
print(tables)

for table in tables:
    print(f"\n=== Table: {table} ===")
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [c[1] for c in cursor.fetchall()]
    print("Columns:", columns)
    
    cursor.execute(f"SELECT * FROM {table}")
    rows = cursor.fetchall()
    print("Rows count:", len(rows))
    for row in rows[:5]:
        print(row)

conn.close()
