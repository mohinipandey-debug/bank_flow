import sqlite3
from config import DATABASE_FILE
from database import init_db

# Run init_db to create the new table if it doesn't exist yet
init_db()

conn = sqlite3.connect(DATABASE_FILE)
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]
print("manual_investments exists:", "manual_investments" in tables)

cols = [r[1] for r in conn.execute(
    "PRAGMA table_info(manual_investments)"
).fetchall()]
print("Columns:", cols)
conn.close()
