"""
Worker Registry: Register DeviceWorkers by (device_id, package) for lookup by Monitors/other components.
Key format: device_id:package (matches worker_node in DeviceWorker).
"""
import threading
from typing import Any, Optional

_registry: dict[str, Any] = {}
_lock = threading.RLock()


def _key(device_id: str, package: str) -> str:
    return f"{device_id}:{package}"


def register_worker(device_id: str, package: str, worker: Any) -> None:
    """Register a worker for lookup. Overwrites if already registered."""
    with _lock:
        _registry[_key(device_id, package)] = worker


def get_worker(device_id: str, package: str) -> Optional[Any]:
    """Get worker by device_id and package. Returns None if not found."""
    with _lock:
        return _registry.get(_key(device_id, package))


def unregister_worker(device_id: str, package: str) -> None:
    """Unregister a worker when it stops."""
    with _lock:
        _registry.pop(_key(device_id, package), None)


def list_workers() -> list[tuple[str, str]]:
    """List all registered (device_id, package) pairs."""
    with _lock:
        return [tuple(k.split(":", 1)) for k in _registry.keys()]
