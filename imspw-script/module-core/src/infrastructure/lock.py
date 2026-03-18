import os
import time
from typing import Optional

class FileLock:
    """
    A simple file-based lock for cross-process synchronization.
    """
    def __init__(self, lock_file: str):
        self.lock_file = lock_file
        self._fd: Optional[int] = None

    def acquire(self, timeout: float = 10.0, poll_interval: float = 0.5) -> bool:
        """
        Acquire the lock.
        
        Args:
            timeout: Maximum time to wait in seconds.
            poll_interval: Time to wait between retries.
            
        Returns:
            True if acquired, False if timeout.
        """
        start_time = time.time()
        while True:
            try:
                self._fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                return True
            except FileExistsError:
                # Check for stale lock
                try:
                    stats = os.stat(self.lock_file)
                    # If lock file is older than 60 seconds, consider it stale and remove it
                    if time.time() - stats.st_mtime > 60:
                        try:
                            os.unlink(self.lock_file)
                            continue # Retry immediately
                        except OSError:
                            pass
                except OSError:
                    pass

                if time.time() - start_time > timeout:
                    return False
                time.sleep(poll_interval)
            except OSError:
                return False

    def release(self):
        """Release the lock."""
        if self._fd is not None:
            try:
                os.close(self._fd)
                os.unlink(self.lock_file)
            except OSError:
                pass
            finally:
                self._fd = None
    
    def __enter__(self):
        if not self.acquire():
             raise TimeoutError(f"Could not acquire lock: {self.lock_file}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
