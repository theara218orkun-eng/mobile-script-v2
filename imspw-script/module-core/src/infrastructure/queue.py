import os
import sqlite3
import json
import time
import threading
from typing import Dict, Any, Optional

# Task priority: lower = run first. LINE first, then Messenger, then others.
# Prevents Messenger from "interrupting" LINE reply when both have incoming.
_TASK_PRIORITY = {
    "REPLY_LINE": 0,
    "REPLY_MESSENGER": 1,
    "REPLY_WHATSAPP": 2,
    "REPLY_WHATSAPP_GROUP": 2,
    "REPLY_TELEGRAM": 3,
}

def _task_priority_order_sql() -> str:
    """Build ORDER BY clause: priority first, then created_at."""
    cases = " ".join(
        f"WHEN '{k}' THEN {v}" for k, v in _TASK_PRIORITY.items()
    )
    return f"CASE task_type {cases} ELSE 99 END, created_at ASC"


class SQLiteQueue:
    """
    A persistent queue implementation using SQLite.
    Supports multi-process access and device-specific queues.
    Uses TASKS_DB_PATH env (set by main.py) so truncate and app share same DB.
    """
    
    def __init__(self, db_path: str = "tasks.db"):
        self.db_path = os.environ.get("TASKS_DB_PATH", db_path)
        self.local = threading.local()
        self._init_db()

    def _get_conn(self):
        # SQLite connections are not thread-safe, so we use thread-local storage
        if not hasattr(self.local, "conn"):
            self.local.conn = sqlite3.connect(self.db_path)
            self.local.conn.row_factory = sqlite3.Row
        return self.local.conn

    def _init_db(self):
        """Initialize the database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT DEFAULT 'PENDING',
                    created_at REAL,
                    processed_at REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_device_status ON task_queue (device_id, status)")
            conn.commit()

    def put(self, device_id: str, task_type: str, payload: Dict[str, Any]) -> int:
        """
        Add a task to the queue.
        
        Args:
            device_id: Target device ID
            task_type: Type of task (e.g., 'SEND_MESSAGE')
            payload: Task data
            
        Returns:
            Task ID
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO task_queue (device_id, task_type, payload, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (device_id, task_type, json.dumps(payload), 'PENDING', time.time())
        )
        conn.commit()
        return cursor.lastrowid

    def get_next(self, device_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the next PENDING task for a specific device.
        Does NOT lock the task; ensuring exclusive execution is the caller's responsibility (via FileLock).
        Prefer claim_next() to avoid the same task being run by multiple workers.
        """
        conn = self._get_conn()
        order_clause = _task_priority_order_sql()
        cursor = conn.execute(
            f"""
            SELECT id, device_id, task_type, payload, created_at 
            FROM task_queue 
            WHERE device_id = ? AND status = 'PENDING' 
            ORDER BY {order_clause}
            LIMIT 1
            """,
            (device_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "id": row["id"],
                "device_id": row["device_id"],
                "task_type": row["task_type"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"]
            }
        return None

    def claim_next(self, device_id: str) -> Optional[Dict[str, Any]]:
        """
        Atomically claim the next PENDING task for this device (set status to IN_PROGRESS).
        Only one worker (across processes) can claim a given task; prevents duplicate execution.
        """
        conn = self._get_conn()
        order_clause = _task_priority_order_sql()
        cursor = conn.execute(
            f"""
            UPDATE task_queue SET status = 'IN_PROGRESS'
            WHERE id = (
                SELECT id FROM task_queue
                WHERE device_id = ? AND status = 'PENDING'
                ORDER BY {order_clause}
                LIMIT 1
            )
            RETURNING id, device_id, task_type, payload, created_at
            """,
            (device_id,),
        )
        row = cursor.fetchone()
        conn.commit()
        if row:
            return {
                "id": row["id"],
                "device_id": row["device_id"],
                "task_type": row["task_type"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"]
            }
        return None

    def mark_done(self, task_id: int):
        """Mark a task as COMPLETED."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE task_queue SET status = 'COMPLETED', processed_at = ? WHERE id = ?",
            (time.time(), task_id)
        )
        conn.commit()

    def mark_failed(self, task_id: int, error: str = ""):
        """Mark a task as FAILED."""
        # We could add an error column, but for now just marking status
        conn = self._get_conn()
        conn.execute(
            "UPDATE task_queue SET status = 'FAILED', processed_at = ? WHERE id = ?",
            (time.time(), task_id)
        )
        conn.commit()

    def reset_to_pending(self, task_id: int):
        """Set task back to PENDING (e.g. when lock was never acquired so another worker can claim it)."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE task_queue SET status = 'PENDING' WHERE id = ? AND status = 'IN_PROGRESS'",
            (task_id,)
        )
        conn.commit()

    def clear(self, device_id: Optional[str] = None):
        """Clear tasks (mostly for testing)."""
        conn = self._get_conn()
        if device_id:
            conn.execute("DELETE FROM task_queue WHERE device_id = ?", (device_id,))
        else:
            conn.execute("DELETE FROM task_queue")
        conn.commit()

    def close(self):
        """Close the thread-local connection."""
        if hasattr(self.local, "conn"):
            self.local.conn.close()
            del self.local.conn
