#!/usr/bin/env python3
"""
Truncate task_queue in tasks.db.
Usage: uv run python scripts/truncate_task_queue.py

IMPORTANT: Stop the main app (Ctrl+C) before truncating, otherwise tasks
already claimed by the worker will still run (they're in memory).
"""
import os
import sqlite3
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
db_path = os.path.join(project_root, "tasks.db")


def main():
    if not os.path.exists(db_path):
        print(f"[OK] {db_path} does not exist (nothing to truncate)")
        return 0

    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT COUNT(*) FROM task_queue")
    count = cur.fetchone()[0]
    conn.execute("DELETE FROM task_queue")
    # Reset AUTOINCREMENT so next task id starts from 1
    conn.execute("DELETE FROM sqlite_sequence WHERE name='task_queue'")
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    conn.close()
    print(f"[OK] Truncated task_queue: deleted {count} rows from {db_path}")
    print(f"     Next task id will be 1. Restart the main app to pick up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
