#!/usr/bin/env python3
"""Print a compact runtime and simplex-iteration overview of stepwise runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path


RESULTS_DIR = Path(
    "/scratch/htc/lmehl/master_thesis/warm_start_experiments/"
    "two_stage_stochastic-stepwise_solving/results"
)


def number(value: object) -> str:
    if value is None or value == "":
        return "-"
    return f"{float(value):.2f}"


def integer(value: object) -> str:
    if value is None or value == "":
        return "-"
    return str(int(float(value)))


def final_step(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))[-1]


def main() -> int:
    print(
        f"{'solver':<8} {'strategy':<21} {'status':<9} {'rep':>3} {'steps':>5} "
        f"{'total_s':>10} {'total_iter':>11} {'final_s':>10} {'final_iter':>11}"
    )
    print("-" * 104)
    for report_path in sorted(RESULTS_DIR.glob("run_*/stepwise_report.json")):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for repetition in report.get("repetitions", []):
            steps = final_step(Path(repetition.get("steps_csv", "")))
            total_runtime = steps.get("cumulative_runtime_s")
            total_iterations = steps.get("cumulative_simplex_iterations")
            print(
                f"{report.get('solver', '-'): <8} {report.get('strategy', '-'): <21} "
                f"{repetition.get('status', report.get('status', '-')): <9} "
                f"{str(repetition.get('repetition', '-')):>3} "
                f"{str(repetition.get('steps', '-')):>5} "
                f"{number(total_runtime):>10} {integer(total_iterations):>11} "
                f"{number(repetition.get('solve_time_s')):>10} "
                f"{integer(repetition.get('simplex_iterations')):>11}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
