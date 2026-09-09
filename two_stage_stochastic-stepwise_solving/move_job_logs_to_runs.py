#!/usr/bin/env python3
"""Move completed SLURM .out/.err pairs into their recorded run directories."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


SCRIPT_DIR = Path("/scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic-stepwise_solving")
JOB_OUT_DIR = SCRIPT_DIR / "results" / "job_out"
OUTPUT_DIR_PATTERN = re.compile(r'"output_dir":\s*"([^"]+)"')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print planned moves without changing files.")
    args = parser.parse_args()

    moved = skipped = 0
    for out_path in sorted(JOB_OUT_DIR.glob("sbatch_job_*.out")):
        match = OUTPUT_DIR_PATTERN.search(out_path.read_text(encoding="utf-8", errors="replace"))
        if match is None:
            print(f"SKIP {out_path.name}: no completed run output_dir")
            skipped += 1
            continue

        destination = Path(match.group(1))
        if not destination.is_dir():
            print(f"SKIP {out_path.name}: destination does not exist: {destination}")
            skipped += 1
            continue

        err_path = out_path.with_suffix(".err")
        for source in (out_path, err_path):
            if not source.exists():
                continue
            target = destination / source.name
            if target.exists():
                print(f"SKIP {source.name}: target already exists: {target}")
                skipped += 1
                continue
            print(f"MOVE {source} -> {target}")
            if not args.dry_run:
                shutil.move(source, target)
                moved += 1

    print(f"Moved {moved} files; skipped {skipped} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
