#!/usr/bin/env python3
"""Benchmark SmartVA generation throughput for selected batch sizes.

Usage (inside Docker):
  docker compose exec minerva_app_service \
    uv run python scripts/benchmark_smartva_batches.py --form-id ICMR01PY0101

By default, runs in rollback mode:
- uses the production SmartVA service functions
- flushes instead of committing DB writes
- skips persisting SmartVA workspace copies
- rolls back DB state after each timing run

Use --commit only if you explicitly want to persist generated SmartVA rows.
"""

from __future__ import annotations

import argparse
import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

import sqlalchemy as sa

from app import create_app, db
from app.models import VaForms
from app.services import smartva_service

DEFAULT_SIZES = (1, 5, 10, 50)


@dataclass(frozen=True)
class BenchmarkRun:
    size: int
    mode: str
    elapsed_seconds: float
    result_rows_saved: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark SmartVA throughput for 1/5/10/50 submission runs.",
    )
    parser.add_argument(
        "--form-id",
        required=True,
        help="Form ID to benchmark against. Must have enough pending SmartVA submissions.",
    )
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=list(DEFAULT_SIZES),
        help="Batch sizes to benchmark. Default: 1 5 10 50",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="How many times to repeat each size. Default: 1",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist SmartVA results instead of rolling them back after each run.",
    )
    return parser.parse_args()


def _load_form(form_id: str) -> VaForms:
    va_form = db.session.get(VaForms, form_id)
    if va_form is None:
        raise SystemExit(f"Form not found: {form_id}")
    return va_form


def _pending_sids(form_id: str) -> list[str]:
    pending = sorted(smartva_service.pending_smartva_sids(form_id))
    if not pending:
        raise SystemExit(
            f"No pending SmartVA submissions found for {form_id}. "
            "Pick a form with current-payload SmartVA backlog."
        )
    return pending


@contextmanager
def _rollback_mode():
    original_commit = db.session.commit
    original_copy_workspace = smartva_service._copy_form_run_workspace

    def _flush_only():
        db.session.flush()

    db.session.commit = _flush_only
    smartva_service._copy_form_run_workspace = lambda *args, **kwargs: None
    try:
        yield
    finally:
        try:
            db.session.rollback()
        finally:
            db.session.remove()
            db.session.commit = original_commit
            smartva_service._copy_form_run_workspace = original_copy_workspace


def _time_call(fn: Callable[[], int]) -> tuple[float, int]:
    started = time.perf_counter()
    saved = fn()
    elapsed = time.perf_counter() - started
    return elapsed, int(saved or 0)


def _run_single_submission(va_sid: str) -> tuple[float, int]:
    return _time_call(
        lambda: smartva_service.generate_for_submission(
            va_sid,
            trigger_source="benchmark_single",
        )
    )


def _run_form_batch(form_id: str, batch_sids: list[str], size: int) -> tuple[float, int]:
    return _time_call(
        lambda: smartva_service.generate_for_form(
            _load_form(form_id),
            target_sids=set(batch_sids),
            trigger_source=f"benchmark_batch_{size}",
        )
    )


def _run_benchmark(form_id: str, candidate_sids: list[str], size: int) -> BenchmarkRun:
    batch_sids = candidate_sids[:size]
    if len(batch_sids) < size:
        raise SystemExit(
            f"Form {form_id} has only {len(candidate_sids)} pending SmartVA submission(s); "
            f"cannot benchmark size {size}."
        )

    if size == 1:
        elapsed, saved = _run_single_submission(batch_sids[0])
        mode = "generate_for_submission"
    else:
        elapsed, saved = _run_form_batch(form_id, batch_sids, size)
        mode = "generate_for_form"
    return BenchmarkRun(
        size=size,
        mode=mode,
        elapsed_seconds=elapsed,
        result_rows_saved=saved,
    )


def _print_header(form_id: str, commit: bool, repetitions: int, max_pending: int) -> None:
    print(f"SmartVA benchmark form: {form_id}")
    print(f"Mode: {'commit' if commit else 'rollback'}")
    print(f"Repetitions: {repetitions}")
    print(f"Pending candidates available: {max_pending}")
    print()


def _print_results(results: list[BenchmarkRun]) -> None:
    print("size\tmode\telapsed_s\tresult_rows_saved")
    for result in results:
        print(
            f"{result.size}\t{result.mode}\t"
            f"{result.elapsed_seconds:.3f}\t{result.result_rows_saved}"
        )
    print()

    grouped: dict[int, list[BenchmarkRun]] = {}
    for result in results:
        grouped.setdefault(result.size, []).append(result)

    print("summary")
    print("size\truns\tavg_s\tmin_s\tmax_s")
    for size in sorted(grouped):
        runs = grouped[size]
        timings = [run.elapsed_seconds for run in runs]
        print(
            f"{size}\t{len(runs)}\t"
            f"{statistics.mean(timings):.3f}\t"
            f"{min(timings):.3f}\t"
            f"{max(timings):.3f}"
        )


def main() -> int:
    args = _parse_args()
    app = create_app()

    with app.app_context():
        _load_form(args.form_id)
        candidate_sids = _pending_sids(args.form_id)
        required = max(args.sizes)
        if len(candidate_sids) < required:
            raise SystemExit(
                f"Form {args.form_id} has only {len(candidate_sids)} pending SmartVA submission(s); "
                f"need at least {required}."
            )

        _print_header(
            form_id=args.form_id,
            commit=args.commit,
            repetitions=args.repetitions,
            max_pending=len(candidate_sids),
        )

        all_results: list[BenchmarkRun] = []
        for repetition in range(args.repetitions):
            if args.repetitions > 1:
                print(f"repetition {repetition + 1}/{args.repetitions}")
            for size in args.sizes:
                if args.commit:
                    result = _run_benchmark(args.form_id, candidate_sids, size)
                    db.session.commit()
                else:
                    with _rollback_mode():
                        result = _run_benchmark(args.form_id, candidate_sids, size)
                all_results.append(result)

        _print_results(all_results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
