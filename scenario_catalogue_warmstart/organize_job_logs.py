#!/usr/bin/env python3
"""Move successful SLURM .out/.err pairs from job_out into their run folder."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import sys


RUN_NAME = r"run_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}"
COPIED_PARAMETER_RE = re.compile(rf"/results/({RUN_NAME})/input_parameters(?:\.\w+)?(?=\s|$)")
GENERATED_ARTIFACT_RE = re.compile(rf"/results/({RUN_NAME})/(?:optimal_bases|ebf_bases|logs)/")
COMPLETION_RE = re.compile(rf"^Finished\. Results:\s+.*?/results/({RUN_NAME})\s*$", re.MULTILINE)
SUMMARY_RESULTS_RE = re.compile(rf"^Results\s*:\s+.*?/results/({RUN_NAME})\s*$", re.MULTILINE)
FAILED_RUNS_RE = re.compile(r"^Not solved to optimality\s*:\s*(\d+)\s*$", re.MULTILINE)
OUTPUT_FOLDER_RE = re.compile(r"^Output folder\s*:\s*(.+?)\s*$", re.MULTILINE)
FAILURE_MARKERS = (
    "PREFLIGHT CHECK FAILED:",
    "FATAL ERROR:",
    "ERROR:",
    "Traceback (most recent call last):",
    "BASIS_READ_ERROR",
)


def parse_arguments():
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-out-dir", type=Path, default=script_dir / "results" / "job_out")
    parser.add_argument("--results-dir", type=Path, default=script_dir / "results")
    parser.add_argument("--move", action="store_true", help="Move verified pairs (default: report only).")
    parser.add_argument("--force", action="store_true", help="Allow moves despite log errors or missing completion output.")
    return parser.parse_args()


def target_run_name(output_text):
    explicit = [Path(path.strip()).name for path in OUTPUT_FOLDER_RE.findall(output_text)]
    references = (
        COPIED_PARAMETER_RE.findall(output_text)
        + GENERATED_ARTIFACT_RE.findall(output_text)
        + completion_run_names(output_text)
    )
    candidates = explicit + references
    if len(candidates) < 2:
        return None, "fewer than two run-folder references"
    if len(set(candidates)) != 1:
        return None, "run-folder references disagree: " + ", ".join(sorted(set(candidates)))
    return candidates[0], None


def completion_run_names(output_text):
    return COMPLETION_RE.findall(output_text)+SUMMARY_RESULTS_RE.findall(output_text)


def check_pair(out_path, err_path, results_dir, force):
    if not err_path.is_file():
        return None, f"missing companion file: {err_path.name}"
    if err_path.stat().st_size and not force:
        return None, f"nonempty error log: {err_path.name}"
    output_text = out_path.read_text(encoding="utf-8", errors="replace")
    markers = [marker for marker in FAILURE_MARKERS if marker in output_text]
    if markers and not force:
        return None, "failure marker(s): " + ", ".join(markers)
    failed_runs = FAILED_RUNS_RE.findall(output_text)
    if failed_runs and int(failed_runs[-1]) and not force:
        return None, f"experiment summary reports {failed_runs[-1]} run(s) not solved to optimality"
    run_name, reason = target_run_name(output_text)
    if reason:
        return None, reason
    if run_name not in completion_run_names(output_text) and not force:
        return None, "missing successful completion line for the detected run folder"
    target_dir = results_dir / run_name
    if not target_dir.is_dir():
        return None, f"target run folder does not exist: {target_dir}"
    existing_logs = [path.name for path in target_dir.iterdir() if path.is_file() and path.suffix in {".out", ".err"}]
    if existing_logs:
        return None, "target already contains .out/.err file(s): " + ", ".join(sorted(existing_logs))
    return target_dir, None


def main():
    args = parse_arguments()
    job_out_dir = args.job_out_dir.expanduser().resolve()
    results_dir = args.results_dir.expanduser().resolve()
    if not job_out_dir.is_dir():
        print(f"ERROR: job output directory does not exist: {job_out_dir}", file=sys.stderr)
        return 2
    if not results_dir.is_dir():
        print(f"ERROR: results directory does not exist: {results_dir}", file=sys.stderr)
        return 2

    out_files = sorted(job_out_dir.glob("*.out"))
    if not out_files:
        print(f"No .out files found in {job_out_dir}")
        return 0

    moved_or_ready = 0
    skipped = 0
    for out_path in out_files:
        err_path = out_path.with_suffix(".err")
        target_dir, reason = check_pair(out_path, err_path, results_dir, args.force)
        if reason:
            skipped += 1
            print(f"SKIP {out_path.name}: {reason}")
            continue
        action = "MOVE" if args.move else "READY"
        if args.force:
            action += " (forced)"
        print(f"{action} {out_path.name}, {err_path.name} -> {target_dir}")
        if args.move:
            shutil.move(str(out_path), target_dir / out_path.name)
            shutil.move(str(err_path), target_dir / err_path.name)
        moved_or_ready += 1
    print(f"\n{('Moved' if args.move else 'Ready')}: {moved_or_ready}; skipped: {skipped}")
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
