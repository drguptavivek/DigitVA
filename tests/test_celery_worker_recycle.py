"""A worker child is recycled mainly on memory (bead digitva-96ik).

The old 100-task recycle idled the worker ~1-4 s and dropped SmartVA's cached
models every 100 tasks, which skipped duplicate SmartVA tasks reach quickly; a
1000-task recycle stays as a safety net (owner 2026-10-23).
"""
from config import Config


def test_worker_children_recycle_on_memory_with_a_rare_count_backstop():
    assert Config.CELERY["worker_max_tasks_per_child"] == 1000
    assert Config.CELERY["worker_max_memory_per_child"] == 300000


def test_worker_has_low_cpu_weight_so_it_yields_cpu_to_gunicorn():
    """Beads digitva-295w, g8iu: p50 was 2.5-6x lower with the worker paused.

    nice only ranks processes inside the worker's own cgroup; cpu_shares 128
    (cpu.weight ~21 vs the app's 100) is what moves CPU to gunicorn.
    """
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parent.parent
    for compose, service in (
        ("docker-compose.yml", "minerva_celery_worker"),
        ("docker-compose.demo.yml", "demo_celery_worker"),
    ):
        services = yaml.safe_load((root / compose).read_text())["services"]
        assert services[service]["cpu_shares"] == 128, compose
        command = services[service]["command"]
        assert command.startswith("nice -n 10 celery "), compose
        assert "--max-memory-per-child=300000" in command, compose
