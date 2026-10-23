"""A worker child is recycled on memory, not on task count (bead digitva-96ik).

A count recycle idled the worker ~1-4 s and dropped SmartVA's cached models
every 100 tasks, which skipped duplicate SmartVA tasks reach quickly.
"""
from config import Config


def test_worker_children_recycle_on_memory_only():
    assert Config.CELERY["worker_max_tasks_per_child"] is None
    assert Config.CELERY["worker_max_memory_per_child"] == 300000
