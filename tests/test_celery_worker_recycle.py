"""A worker child is recycled mainly on memory (bead digitva-96ik).

The old 100-task recycle idled the worker ~1-4 s and dropped SmartVA's cached
models every 100 tasks, which skipped duplicate SmartVA tasks reach quickly; a
1000-task recycle stays as a safety net (owner 2026-10-23).
"""
from config import Config


def test_worker_children_recycle_on_memory_with_a_rare_count_backstop():
    assert Config.CELERY["worker_max_tasks_per_child"] == 1000
    assert Config.CELERY["worker_max_memory_per_child"] == 300000
