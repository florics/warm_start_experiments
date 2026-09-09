#!/usr/bin/env python3
"""Generate two source bases and validate a two-stage BAS warm start.

Use the supplied parameter file unchanged. The dedicated no-presolve parameter
files are available as an optional diagnostic mode.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = PROJECT_ROOT / "generate_solver_bases" / "generate_bases.py"
CONSTRUCTOR = PROJECT_ROOT / "two_stage_stochastic" / "construct_two_stage_basis.py"


def run(command: list[str], measure: bool) -> None:
    if measure:
        perf = shutil.which("perf")
        if perf is None:
            print("WARNING: perf is unavailable; collecting /usr/bin/time -v only.", file=sys.stderr)
            command = ["/usr/bin/time", "-v", *command]
        else:
            command = [
                "/usr/bin/time", "-v", perf, "stat", "-e",
                "cycles,instructions,task-clock,cpu-clock", "--", *command,
            ]
    print("Running:", " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, check=True)


def write_csvs(directory: Path, solver: str, parameter_file: Path, first_lp: Path, second_lp: Path) -> tuple[Path, Path]:
    instances = directory / "instances.csv"
    parameters = directory / "parameters.csv"
    with instances.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "lp_file"])
        writer.writerow(["scenario_a", first_lp])
        writer.writerow(["scenario_b", second_lp])
    with parameters.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["solver", "parameter_name", "parameter_file"])
        writer.writerow([solver, "correctness", parameter_file])
    return instances, parameters


def source_basis_paths(run_directory: Path) -> tuple[Path, Path]:
    with (run_directory / "summary.csv").open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_name = {row["instance_name"]: row for row in rows}
    missing = [name for name in ("scenario_a", "scenario_b") if name not in by_name]
    failed = [row for row in rows if row.get("result") != "OK"]
    if missing or failed:
        raise RuntimeError(f"Source basis generation failed: missing={missing}, failed={failed}")
    return Path(by_name["scenario_a"]["basis_file"]), Path(by_name["scenario_b"]["basis_file"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("solver", choices=["gurobi", "copt", "highs", "xpress"])
    parser.add_argument("first_lp", type=Path)
    parser.add_argument("second_lp", type=Path)
    parser.add_argument("integrated_lp", type=Path)
    parser.add_argument("parameter_file", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--scenario-a", required=True)
    parser.add_argument("--scenario-b", required=True)
    parser.add_argument("--measure", action=argparse.BooleanOptionalAction, default=True, help="measure source-basis generation and each integrated repetition with /usr/bin/time -v and perf stat")
    parser.add_argument("--no-solve", action="store_true", help="construct and validate the BAS, but do not solve the integrated LP")
    parser.add_argument("--no-check-initial-dual-feasibility", action="store_true")
    parser.add_argument("--run-label", help="optional descriptive suffix for the constructor's timestamped run directory")
    parser.add_argument("--repetitions", type=int, default=1, help="number of fresh integrated warm-start solves")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    for path in (args.first_lp, args.second_lp, args.integrated_lp, args.parameter_file):
        if not path.is_file():
            parser.error(f"File not found: {path}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    input_dir = args.output_dir / "input"
    input_dir.mkdir(exist_ok=True)
    instances, parameters = write_csvs(input_dir, args.solver, args.parameter_file, args.first_lp, args.second_lp)
    generation_root = args.output_dir / "source_basis_generation"
    print(
        "[PHASE] SOURCE_BASIS_GENERATION: purpose=solve each single-scenario LP and write its source BAS.",
        flush=True,
    )
    print(f"[INPUT] First scenario LP: {args.first_lp}", flush=True)
    print(f"[INPUT] Second scenario LP: {args.second_lp}", flush=True)
    print(f"[INPUT] Integrated two-stage LP: {args.integrated_lp}", flush=True)
    run([sys.executable, str(GENERATOR), str(instances), str(parameters), str(generation_root)], args.measure)
    runs = sorted(generation_root.glob("run_*"), key=lambda path: path.stat().st_mtime)
    if not runs:
        raise RuntimeError("Basis generator did not create a run directory")
    first_bas, second_bas = source_basis_paths(runs[-1])
    command = [
        sys.executable, str(CONSTRUCTOR), args.solver,
        str(args.first_lp), str(first_bas), str(args.second_lp), str(second_bas),
        str(args.integrated_lp),
        "--scenario-a", args.scenario_a, "--scenario-b", args.scenario_b,
        "--output-parent", str(args.output_dir),
    ]
    if args.run_label:
        command.extend(["--run-label", args.run_label])
    command.extend(["--repetitions", str(args.repetitions)])
    if not args.no_solve:
        command.extend(["--parameter-file", str(args.parameter_file), "--solve"])
        command.append("--measure" if args.measure else "--no-measure")
        if args.no_check_initial_dual_feasibility:
            command.append("--no-check-initial-dual-feasibility")
    print(
        "[PHASE] INTEGRATED_WARMSTART_VALIDATION: purpose=merge source BAS files, load the result "
        "into the integrated LP, and run the configured warm-start solve.",
        flush=True,
    )
    # The constructor owns per-repetition measurements; wrapping it here would
    # only add a redundant aggregate measurement around all repetitions.
    run(command, False)
    print(f"Source bases: {first_bas}, {second_bas}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
