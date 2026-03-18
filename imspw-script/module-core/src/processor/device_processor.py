import os
import threading
import time
import traceback
from typing import Dict, Any, Callable

from aid_utils import safe_print, logger
from infrastructure.queue import SQLiteQueue
from infrastructure.lock import FileLock

class DeviceProcessor:
    """
    Manages task execution for a specific device, ensuring sequential processing
    and exclusive access via persistent queue and file locks.
    """
    
    def __init__(self, device_id: str):
        self.device_id = str(device_id).strip()
        self.queue = SQLiteQueue()
        safe_id = self.device_id.replace(":", "_").replace("@", "_")
        # Absolute path so multiple processes share the same lock (prevents duplicate send)
        queue_dir = os.path.dirname(os.path.abspath(getattr(self.queue, "db_path", "tasks.db")))
        self.lock_file = os.path.join(queue_dir, f"device_{safe_id}.lock")
        self.is_running = True
        self.handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name=f"Processor-{self.device_id}")

    def start(self):
        """Starts the processor worker loop if not already running."""
        if not self.worker_thread.is_alive():
            try:
                self.worker_thread.start()
            except RuntimeError:
                pass

    def register_handler(self, task_type: str, handler: Callable[[Dict[str, Any]], None]):
        """Register a handler for a specific task type on this processor."""
        self.handlers[task_type] = handler

    def add_task(self, task_type: str, payload: Dict[str, Any] = None) -> int:
        """Add a persistent task to the queue."""
        if payload is None:
            payload = {}
        return self.queue.put(self.device_id, task_type, payload)

    def _worker_loop(self):
        safe_print(f"[{self.device_id}] [Processor] Started with persistent queue.")
        while self.is_running:
            try:
                # 1. Atomically claim next task (so only one worker runs it, prevents duplicate send)
                task = self.queue.claim_next(self.device_id)
                if not task:
                    time.sleep(1.0)
                    continue

                task_id = task["id"]
                task_type = task["task_type"]
                payload = task["payload"]
                safe_print(f"[{self.device_id}] [Processor] Picked up task {task_id}: {task_type}")

                # 2. Acquire lock (serialize execution per device; lock path is absolute so multi-process shares it)
                lock = FileLock(self.lock_file)
                if lock.acquire(timeout=5.0):
                    try:
                        self._process_task(task_type, payload)
                        self.queue.mark_done(task_id)
                        safe_print(f"[{self.device_id}] [Processor] Task {task_id} completed.")
                    except Exception as e:
                        logger.error(f"[{self.device_id}] [Processor] Task {task_id} failed: {e}")
                        traceback.print_exc()
                        self.queue.mark_failed(task_id)
                    finally:
                        lock.release()
                else:
                    safe_print(f"[{self.device_id}] [Processor] Could not acquire lock for task {task_id}. Re-queuing...")
                    self.queue.reset_to_pending(task_id)
                    time.sleep(2.0)

            except Exception as e:
                logger.error(f"[{self.device_id}] [Processor] Loop Error: {e}")
                time.sleep(5.0)

    def _process_task(self, task_type: str, payload: Dict[str, Any]):
        """Dispatch task to registered handler."""
        handler = self.handlers.get(task_type)
        if handler:
            handler(payload)
        else:
            raise ValueError(f"No handler registered for task type: {task_type}")

# Singleton Management
_PROCESSORS: Dict[str, DeviceProcessor] = {}
_LOCK = threading.Lock()

def get_device_processor(device_id: str) -> DeviceProcessor:
    with _LOCK:
        if device_id not in _PROCESSORS:
            _PROCESSORS[device_id] = DeviceProcessor(device_id)
        return _PROCESSORS[device_id]
