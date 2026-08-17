#!/usr/bin/env python3
"""Compare two EBF files or two complete EBF bases.

All EBF inputs may be plain CSV, .csv.gz, or a single-member .zip archive.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from basis_tools.ebf import compare_ebf_bases, compare_ebf_files


def main():
    parser = argparse.ArgumentParser(description="Compare Explicit Basis Format files")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("file", help="Compare two variable EBFs or two constraint EBFs")
    one.add_argument("first")
    one.add_argument("second")
    one.add_argument("--tolerance", type=float, default=0.0)

    basis = sub.add_parser("basis", help="Compare two complete EBF bases")
    basis.add_argument("first_vars")
    basis.add_argument("first_constrs")
    basis.add_argument("second_vars")
    basis.add_argument("second_constrs")
    basis.add_argument("--tolerance", type=float, default=0.0)

    args = parser.parse_args()
    if args.tolerance < 0:
        parser.error("--tolerance must be nonnegative")

    if args.command == "file":
        compare_ebf_files(args.first, args.second, numerical_tolerance=args.tolerance)
    else:
        compare_ebf_bases(
            args.first_vars,
            args.first_constrs,
            args.second_vars,
            args.second_constrs,
            numerical_tolerance=args.tolerance,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
