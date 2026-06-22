import os
import sqlite3
from datetime import datetime

DB_PATH = os.getenv("STATS_DB_PATH", "/tmp/markdown_bot/stats.db")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                file_ext TEXT,
                file_size INTEGER,
                success INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


def log_conversion(user_id: int, username: str, file_ext: str, file_size: int, success: bool):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO conversions (user_id, username, file_ext, file_size, success, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, username, file_ext, file_size, int(success), datetime.utcnow().isoformat()),
        )


def get_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM conversions").fetchone()[0]
        success = conn.execute("SELECT COUNT(*) FROM conversions WHERE success=1").fetchone()[0]
        users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM conversions").fetchone()[0]
        top_formats = conn.execute(
            "SELECT file_ext, COUNT(*) as cnt FROM conversions GROUP BY file_ext ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
    return {"total": total, "success": success, "users": users, "top_formats": top_formats}
