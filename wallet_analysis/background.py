"""
Simple in-process background task runner.

Replaces Celery for development — tasks run in daemon threads
so the Django request returns immediately. Status is stored in
a module-level dict (lost on restart, but fine for dev).
"""

import threading
import traceback
import uuid
from datetime import datetime


# task_id -> {status, progress, result, error, started_at, finished_at}
_tasks: dict = {}
_lock = threading.Lock()


def _set(task_id, **kwargs):
    with _lock:
        _tasks.setdefault(task_id, {})
        _tasks[task_id].update(kwargs)


def get_task(task_id) -> dict:
    with _lock:
        return dict(_tasks.get(task_id, {'status': 'UNKNOWN'}))


def run_in_background(fn, *args, **kwargs) -> str:
    """Run *fn* in a daemon thread. Returns a task_id for polling."""
    task_id = uuid.uuid4().hex[:12]
    _set(task_id, status='PENDING', progress=0, started_at=datetime.utcnow().isoformat())

    def _wrapper():
        try:
            _set(task_id, status='PROGRESS')
            result = fn(task_id, *args, **kwargs)
            _set(task_id, status='SUCCESS', result=result,
                 finished_at=datetime.utcnow().isoformat())
        except Exception as e:
            _set(task_id, status='FAILURE', error=str(e),
                 traceback=traceback.format_exc(),
                 finished_at=datetime.utcnow().isoformat())

    t = threading.Thread(target=_wrapper, daemon=True)
    t.start()
    return task_id


def update_progress(task_id, progress: int, stage: str = '', **extra):
    _set(task_id, progress=progress, stage=stage, **extra)
