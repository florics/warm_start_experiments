#!/usr/bin/env python3
"""Cross-solver basis portability test using the shared basis_tools adapters.

For each selected producer solver:
  1. load and solve the same LP;
  2. export and validate EBF 1.1;
  3. preserve the producer's native basis representation;
  4. write a classical MPS BAS exchange file;
  5. let every selected consumer read that exchange BAS into a fresh LP;
  6. compare BASIC membership immediately after import;
  7. solve so values/row activities are available;
  8. export EBF again and compare producer/consumer EBF.

There is deliberately no EBF -> solver importer here. The test exercises the
same shared adapters used by generate_bases.py and warmstart_batch.py.

Input LPs may be .lp, .lp.gz, or single-member .lp.zip files. With
--compress-output, generated native basis, exchange BAS, and EBF artifacts are
gzip-compressed. ZIP output is not supported.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import os
import sys
import time
import traceback

# Allow direct execution from basis_tools/tests/ without installing a package.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from basis_tools.basis_export import export_ebf
from basis_tools.ebf import (
    BasisStatus,
    compare_ebf_bases,
    get_format_info,
    read_constraint_basis_csv,
    read_variable_basis_csv,
)
from basis_tools.io_utils import output_path, validate_input_suffix
from basis_tools.solver_adapters import SUPPORTED_SOLVERS, get_solver_adapter


PRODUCER_COLUMNS = [
    "timestamp",
    "producer_solver",
    "status",
    "native_basis",
    "exchange_bas",
    "vars_csv",
    "constrs_csv",
    "num_rows",
    "simplex_iterations",
    "log_file",
    "message",
]

TRANSFER_COLUMNS = [
    "timestamp",
    "producer_solver",
    "consumer_solver",
    "status",
    "exchange_bas",
    "pre_solve_var_basis_status_differences",
    "pre_solve_constr_basis_status_differences",
    "consumer_simplex_iterations",
    "producer_vars_csv",
    "producer_constrs_csv",
    "consumer_vars_csv",
    "consumer_constrs_csv",
    "var_basis_status_differences",
    "var_bound_status_differences",
    "var_max_abs_value_difference",
    "var_value_difference_rows",
    "constr_basis_status_differences",
    "constr_bound_status_differences",
    "constr_max_abs_activity_difference",
    "constr_activity_difference_rows",
    "message",
]


def timestamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def create_unique_run_dir(base: Path) -> Path:
    base = base.expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    while True:
        path = base / f"run_{timestamp_now()}"
        if not path.exists():
            path.mkdir()
            return path
        print(f"{path} already exists; waiting one second.")
        time.sleep(1)


def parse_assignments(items):
    result = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Expected SOLVER=FILE, got {item!r}")
        solver, filename = item.split("=", 1)
        solver = solver.strip().lower()
        if solver not in SUPPORTED_SOLVERS:
            raise ValueError(f"Unsupported solver in parameter assignment: {solver}")
        path = Path(filename).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Parameter file not found for {solver}: {path}")
        result[solver] = path
    return result


def write_header(path: Path, columns):
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=columns).writeheader()


def append_row(path: Path, columns, row):
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=columns).writerow(
            {column: row.get(column, "") for column in columns}
        )
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass


def _basis_status_membership_from_ebf(vars_csv, constrs_csv):
    variables = read_variable_basis_csv(vars_csv)
    constraints = read_constraint_basis_csv(constrs_csv)
    return (
        {
            entry.var_name: entry.basis_status == BasisStatus.BASIC
            for entry in variables
        },
        {
            entry.constr_name: entry.basis_status == BasisStatus.BASIC
            for entry in constraints
        },
    )


def _count_membership_differences(reference, observed, entity_kind):
    ref_names = set(reference)
    obs_names = set(observed)
    if ref_names != obs_names:
        missing = sorted(ref_names - obs_names)
        extra = sorted(obs_names - ref_names)
        raise RuntimeError(
            f"{entity_kind} names differ in pre-solve basis snapshot. "
            f"Missing in consumer: {missing[:10]}"
            + (" ..." if len(missing) > 10 else "")
            + f"; extra in consumer: {extra[:10]}"
            + (" ..." if len(extra) > 10 else "")
        )
    return sum(reference[name] != observed[name] for name in ref_names)


def produce_basis(
    solver,
    lp,
    parameter_file,
    producer_dir,
    bound_tolerance,
    *,
    compress_output,
):
    producer_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": timestamp_now(),
        "producer_solver": solver,
        "status": "ERROR",
        "message": "",
    }

    adapter = None
    model = None

    vars_csv = output_path(
        producer_dir / f"{solver}__producer__vars.csv",
        compress=compress_output,
    )
    constrs_csv = output_path(
        producer_dir / f"{solver}__producer__constrs.csv",
        compress=compress_output,
    )
    log_file = producer_dir / f"{solver}__producer.log"

    # HiGHS gets .highs.bas for its native text; other solvers use .bas.
    adapter_for_ext = get_solver_adapter(solver)
    native_basis = output_path(
        producer_dir / f"{solver}__producer_basis{adapter_for_ext.native_basis_extension}",
        compress=compress_output,
    )
    exchange_bas = output_path(
        producer_dir / f"{solver}__producer_basis.bas",
        compress=compress_output,
    )

    row.update(
        vars_csv=str(vars_csv),
        constrs_csv=str(constrs_csv),
        log_file=str(log_file),
        native_basis=str(native_basis),
        exchange_bas=str(exchange_bas),
    )

    try:
        adapter = adapter_for_ext
        model = adapter.load_model(lp)
        adapter.solve(model, parameter_file=parameter_file, log_file=log_file)
        row["simplex_iterations"] = adapter.get_simplex_iterations(model)

        export_ebf(
            adapter,
            model,
            vars_csv,
            constrs_csv,
            tolerance=bound_tolerance,
            validate=True,
            write_before_validation=False,
        )
        row["num_rows"] = adapter.get_num_rows(model)

        adapter.write_native_basis(model, native_basis)
        if not native_basis.is_file():
            raise RuntimeError(
                f"Native basis writer returned without creating {native_basis}"
            )

        adapter.write_exchange_bas(model, native_basis, exchange_bas)
        if not exchange_bas.is_file():
            raise RuntimeError(
                f"Exchange BAS writer returned without creating {exchange_bas}"
            )

        row["status"] = "OK"
        return row, (vars_csv, constrs_csv, native_basis, exchange_bas)

    except Exception as exc:
        row["message"] = f"{exc}; traceback: {traceback.format_exc()}"
        return row, None

    finally:
        if adapter is not None and model is not None:
            try:
                adapter.dispose(model)
            except Exception:
                pass


def consume_basis(
    producer,
    consumer,
    lp,
    exchange_bas,
    producer_ebf,
    parameter_file,
    consumer_dir,
    bound_tolerance,
    compare_tolerance,
    *,
    compress_output,
):
    consumer_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": timestamp_now(),
        "producer_solver": producer,
        "consumer_solver": consumer,
        "status": "ERROR",
        "exchange_bas": str(exchange_bas),
        "message": "",
        "producer_vars_csv": str(producer_ebf[0]),
        "producer_constrs_csv": str(producer_ebf[1]),
    }

    adapter = None
    model = None
    vars_csv = output_path(
        consumer_dir / f"{producer}__basis_read_by__{consumer}__vars.csv",
        compress=compress_output,
    )
    constrs_csv = output_path(
        consumer_dir / f"{producer}__basis_read_by__{consumer}__constrs.csv",
        compress=compress_output,
    )
    log_file = consumer_dir / f"{producer}__basis_read_by__{consumer}.log"
    row.update(
        consumer_vars_csv=str(vars_csv),
        consumer_constrs_csv=str(constrs_csv),
    )

    try:
        adapter = get_solver_adapter(consumer)
        model = adapter.load_model(lp)

        try:
            adapter.read_basis(model, exchange_bas)
        except Exception as exc:
            row["status"] = "BASIS_READ_ERROR"
            row["message"] = str(exc)
            return row

        # Preserve the later diagnostic added to the cross-read test: inspect
        # BASIC membership immediately after basis import and before solving.
        try:
            producer_var_basic, producer_constr_basic = (
                _basis_status_membership_from_ebf(
                    producer_ebf[0], producer_ebf[1]
                )
            )
            consumer_var_basic, consumer_constr_basic = (
                adapter.get_basic_membership(model)
            )
            row["pre_solve_var_basis_status_differences"] = (
                _count_membership_differences(
                    producer_var_basic, consumer_var_basic, "variable"
                )
            )
            row["pre_solve_constr_basis_status_differences"] = (
                _count_membership_differences(
                    producer_constr_basic, consumer_constr_basic, "constraint"
                )
            )
        except Exception as exc:
            row["status"] = "PRE_SOLVE_BASIS_SNAPSHOT_ERROR"
            row["message"] = (
                "Could not inspect native basis immediately after import: "
                f"{exc}"
            )
            return row

        # EBF includes primal values and row activities. The consumer solve is
        # therefore retained exactly as in the working test. With a simplex
        # parameter file and an already-optimal imported basis, this should
        # normally require zero pivots.
        try:
            adapter.solve(model, parameter_file=parameter_file, log_file=log_file)
        except Exception as exc:
            row["status"] = "OPTIMIZE_ERROR"
            row["message"] = str(exc)
            return row

        row["consumer_simplex_iterations"] = adapter.get_simplex_iterations(model)

        export_ebf(
            adapter,
            model,
            vars_csv,
            constrs_csv,
            tolerance=bound_tolerance,
            validate=True,
            write_before_validation=False,
        )

        comparison = compare_ebf_bases(
            producer_ebf[0],
            producer_ebf[1],
            vars_csv,
            constrs_csv,
            numerical_tolerance=compare_tolerance,
            print_result=False,
        )
        v = comparison.variables
        c = comparison.constraints
        row.update(
            status="OK",
            var_basis_status_differences=v.basis_status_differences,
            var_bound_status_differences=v.bound_status_differences,
            var_max_abs_value_difference=(
                ""
                if v.max_abs_numerical_difference is None
                else v.max_abs_numerical_difference
            ),
            var_value_difference_rows=(
                ""
                if v.numerical_difference_rows is None
                else v.numerical_difference_rows
            ),
            constr_basis_status_differences=c.basis_status_differences,
            constr_bound_status_differences=c.bound_status_differences,
            constr_max_abs_activity_difference=(
                ""
                if c.max_abs_numerical_difference is None
                else c.max_abs_numerical_difference
            ),
            constr_activity_difference_rows=(
                ""
                if c.numerical_difference_rows is None
                else c.numerical_difference_rows
            ),
        )
        return row

    except Exception as exc:
        row["message"] = f"{exc}; traceback: {traceback.format_exc()}"
        return row

    finally:
        if adapter is not None and model is not None:
            try:
                adapter.dispose(model)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(
        description=(
            "For each producer solver, transfer its classical .bas exchange "
            "basis to every selected consumer solver and compare EBF exports."
        )
    )
    parser.add_argument("lp_file", help=".lp, .lp.gz, or single-member .lp.zip")
    parser.add_argument(
        "--solvers",
        nargs="+",
        default=list(SUPPORTED_SOLVERS),
        choices=SUPPORTED_SOLVERS,
    )
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="SOLVER=FILE",
        help="Shorthand parameter file used for both producer and consumer roles",
    )
    parser.add_argument(
        "--producer-param", action="append", default=[], metavar="SOLVER=FILE"
    )
    parser.add_argument(
        "--consumer-param", action="append", default=[], metavar="SOLVER=FILE"
    )
    parser.add_argument(
        "--include-same-solver",
        action="store_true",
        help="Also test the exchange-basis round trip within the producer solver",
    )
    parser.add_argument("--bound-tolerance", type=float, default=1e-9)
    parser.add_argument("--compare-tolerance", type=float, default=0.0)
    parser.add_argument(
        "--compress-output",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Compress generated BAS/EBF files with gzip (default: enabled).",
    )
    args = parser.parse_args()

    if args.bound_tolerance < 0 or args.compare_tolerance < 0:
        parser.error("tolerances must be nonnegative")

    lp = Path(args.lp_file).expanduser().resolve()
    if not lp.is_file():
        print(f"LP file not found: {lp}", file=sys.stderr)
        return 1
    try:
        validate_input_suffix(lp, ".lp")
    except Exception as exc:
        print(f"Invalid LP input: {exc}", file=sys.stderr)
        return 1

    try:
        common = parse_assignments(args.param)
        producer_specific = parse_assignments(args.producer_param)
        consumer_specific = parse_assignments(args.consumer_param)
    except Exception as exc:
        print(f"Parameter specification error: {exc}", file=sys.stderr)
        return 1

    producer_params = {**common, **producer_specific}
    consumer_params = {**common, **consumer_specific}
    solvers = list(dict.fromkeys(args.solvers))

    run_dir = create_unique_run_dir(Path(args.out))
    producer_summary = run_dir / "producer_bases.csv"
    transfer_summary = run_dir / "cross_solver_reads.csv"
    write_header(producer_summary, PRODUCER_COLUMNS)
    write_header(transfer_summary, TRANSFER_COLUMNS)

    info = get_format_info()
    with (run_dir / "test_info.txt").open("w", encoding="utf-8") as f:
        f.write(f"Created: {datetime.now().isoformat()}\n")
        f.write(f"LP: {lp}\n")
        f.write(f"Solvers: {', '.join(solvers)}\n")
        f.write(
            f"EBF: {info['name']} ({info['abbreviation']}) "
            f"{info['version']}\n"
        )
        f.write(f"Compressed basis/EBF output: {args.compress_output}\n")
        f.write(
            "Test: producer solve -> native basis -> classical .bas exchange "
            "-> consumer read -> pre-solve BASIC-membership snapshot -> solve "
            "-> EBF comparison\n"
        )

    print(f"Test directory: {run_dir}")
    for producer in solvers:
        print(f"\n=== PRODUCER {producer} ===")
        producer_dir = run_dir / f"producer_{producer}"
        producer_row, produced = produce_basis(
            producer,
            lp,
            producer_params.get(producer),
            producer_dir,
            args.bound_tolerance,
            compress_output=args.compress_output,
        )
        append_row(producer_summary, PRODUCER_COLUMNS, producer_row)
        print(f"producer status: {producer_row['status']}")
        if producer_row.get("message"):
            print(f"producer message: {producer_row['message']}")
        if produced is None:
            continue

        producer_vars, producer_constrs, native_basis, exchange_bas = produced
        for consumer in solvers:
            if consumer == producer and not args.include_same_solver:
                continue
            print(f"  -> {consumer} reads {producer} basis")
            row = consume_basis(
                producer,
                consumer,
                lp,
                exchange_bas,
                (producer_vars, producer_constrs),
                consumer_params.get(consumer),
                producer_dir / f"read_by_{consumer}",
                args.bound_tolerance,
                args.compare_tolerance,
                compress_output=args.compress_output,
            )
            append_row(transfer_summary, TRANSFER_COLUMNS, row)
            print(
                f"     status={row['status']} "
                f"pre_var_basis_diffs="
                f"{row.get('pre_solve_var_basis_status_differences', '')} "
                f"pre_row_basis_diffs="
                f"{row.get('pre_solve_constr_basis_status_differences', '')} "
                f"iterations={row.get('consumer_simplex_iterations', '')} "
                f"post_var_basis_diffs="
                f"{row.get('var_basis_status_differences', '')} "
                f"post_row_basis_diffs="
                f"{row.get('constr_basis_status_differences', '')}"
            )
            if row.get("message"):
                print(f"     message: {row['message']}")

    print(f"\nProducer summary: {producer_summary}")
    print(f"Cross-solver read summary: {transfer_summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
