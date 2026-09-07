#!/usr/bin/env python3
"""Classical MPS BAS helpers and HiGHS native basis conversion."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .io_utils import open_text_read, open_text_write

LOWER = "LOWER"
BASIC = "BASIC"
UPPER = "UPPER"
ZERO = "ZERO"
NONBASIC = "NONBASIC"
HIGHS_INT_TO_STATUS = {0: LOWER, 1: BASIC, 2: UPPER, 3: ZERO, 4: NONBASIC}


@dataclass(frozen=True)
class BasisVectors:
    col_names: list[str]
    row_names: list[str]
    col_status: list[str]
    row_status: list[str]


class BasisFileError(ValueError):
    pass


def first_nonempty_line(path: str | Path) -> str:
    with open_text_read(path) as f:
        for raw in f:
            line = raw.strip()
            if line:
                return line
    raise BasisFileError(f"Basis file is empty: {path}")


def _check_unique(names: Sequence[str], kind: str) -> None:
    if len(set(names)) != len(names):
        raise BasisFileError(f"Model has duplicate {kind} names; name-based BAS conversion is ambiguous")


def _validate_simplex_cardinality(col_status: Sequence[str], row_status: Sequence[str]) -> None:
    allowed = {LOWER, BASIC, UPPER}
    bad_cols = [(i, s) for i, s in enumerate(col_status) if s not in allowed]
    bad_rows = [(i, s) for i, s in enumerate(row_status) if s not in allowed]
    if bad_cols or bad_rows:
        raise BasisFileError(
            "Classical MPS BAS can represent only LOWER/BASIC/UPPER states; "
            f"unsupported columns={bad_cols[:5]}, rows={bad_rows[:5]}"
        )
    m = len(row_status)
    num_basic = sum(s == BASIC for s in col_status) + sum(s == BASIC for s in row_status)
    if num_basic != m:
        raise BasisFileError(f"Invalid LP basis cardinality: BASIC entries={num_basic}, expected rows={m}")
    basic_cols = sum(s == BASIC for s in col_status)
    nonbasic_rows = sum(s != BASIC for s in row_status)
    if basic_cols != nonbasic_rows:
        raise BasisFileError(f"Invalid BAS pairing cardinality: basic columns={basic_cols}, nonbasic rows={nonbasic_rows}")


def parse_mps_bas(path, col_names: Sequence[str], row_names: Sequence[str]) -> BasisVectors:
    path = Path(path)
    col_names, row_names = list(col_names), list(row_names)
    _check_unique(col_names, "column")
    _check_unique(row_names, "row")
    col_index = {name: i for i, name in enumerate(col_names)}
    row_index = {name: i for i, name in enumerate(row_names)}
    col_status = [LOWER] * len(col_names)
    row_status = [BASIC] * len(row_names)
    explicit_cols, explicit_rows = {}, {}
    saw_name = saw_end = False

    def assign_col(name, status, lineno):
        if name not in col_index:
            raise BasisFileError(f"{path}:{lineno}: unknown column {name!r}")
        i = col_index[name]
        old = explicit_cols.get(i)
        if old is not None and old != status:
            raise BasisFileError(f"{path}:{lineno}: conflicting status for column {name!r}: {old} vs {status}")
        explicit_cols[i] = status
        col_status[i] = status

    def assign_row(name, status, lineno):
        if name not in row_index:
            raise BasisFileError(f"{path}:{lineno}: unknown row {name!r}")
        i = row_index[name]
        old = explicit_rows.get(i)
        if old is not None and old != status:
            raise BasisFileError(f"{path}:{lineno}: conflicting status for row {name!r}: {old} vs {status}")
        explicit_rows[i] = status
        row_status[i] = status

    with open_text_read(path) as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            code = parts[0].upper()
            if code == "NAME":
                if saw_name:
                    raise BasisFileError(f"{path}:{lineno}: multiple NAME records")
                saw_name = True
                continue
            if not saw_name:
                raise BasisFileError(f"{path}:{lineno}: first data record must follow NAME")
            if code == "ENDATA":
                saw_end = True
                break
            if code in {"XL", "XU"}:
                if len(parts) != 3:
                    raise BasisFileError(f"{path}:{lineno}: {code} requires column and row names")
                assign_col(parts[1], BASIC, lineno)
                assign_row(parts[2], LOWER if code == "XL" else UPPER, lineno)
            elif code in {"UL", "LL", "BS"}:
                if len(parts) != 2:
                    raise BasisFileError(f"{path}:{lineno}: {code} requires one column name")
                assign_col(parts[1], {"UL": UPPER, "LL": LOWER, "BS": BASIC}[code], lineno)
            else:
                raise BasisFileError(f"{path}:{lineno}: unsupported BAS record {code!r}")
    if not saw_name:
        raise BasisFileError(f"{path}: missing NAME record")
    if not saw_end:
        raise BasisFileError(f"{path}: missing ENDATA record")
    _validate_simplex_cardinality(col_status, row_status)
    return BasisVectors(col_names, row_names, col_status, row_status)


def write_mps_bas(path, col_names, row_names, col_status, row_status, *, problem_name="HIGHSBAS") -> None:
    col_names, row_names = list(col_names), list(row_names)
    col_status, row_status = list(col_status), list(row_status)
    if len(col_names) != len(col_status) or len(row_names) != len(row_status):
        raise BasisFileError("Name/status vector lengths do not match")
    _check_unique(col_names, "column")
    _check_unique(row_names, "row")
    _validate_simplex_cardinality(col_status, row_status)
    basic_cols = [i for i, s in enumerate(col_status) if s == BASIC]
    nonbasic_rows = [i for i, s in enumerate(row_status) if s != BASIC]
    with open_text_write(path, newline="\n") as f:
        f.write(f"NAME          {problem_name}\n")
        for ci, ri in zip(basic_cols, nonbasic_rows):
            code = "XL" if row_status[ri] == LOWER else "XU"
            f.write(f" {code} {col_names[ci]}  {row_names[ri]}\n")
        for i, status in enumerate(col_status):
            if status == UPPER:
                f.write(f" UL {col_names[i]}\n")
        f.write("ENDATA\n")


def rename_basis_vectors(
    basis: BasisVectors,
    column_name_map: dict[str, str],
    row_name_map: dict[str, str],
) -> BasisVectors:
    """Rename a complete basis while retaining its statuses exactly."""
    missing_columns = [name for name in basis.col_names if name not in column_name_map]
    missing_rows = [name for name in basis.row_names if name not in row_name_map]
    if missing_columns or missing_rows:
        raise BasisFileError(
            "Basis name mapping is incomplete: "
            f"columns={missing_columns[:3]}, rows={missing_rows[:3]}"
        )
    new_columns = [column_name_map[name] for name in basis.col_names]
    new_rows = [row_name_map[name] for name in basis.row_names]
    _check_unique(new_columns, "renamed column")
    _check_unique(new_rows, "renamed row")
    _validate_simplex_cardinality(basis.col_status, basis.row_status)
    return BasisVectors(new_columns, new_rows, list(basis.col_status), list(basis.row_status))


def combine_basis_vectors(
    first: BasisVectors,
    second: BasisVectors,
    additional_basic_rows: Sequence[str],
) -> BasisVectors:
    """Block-combine two bases and make every new coupling row BASIC."""
    col_names = [*first.col_names, *second.col_names]
    row_names = [*first.row_names, *second.row_names, *additional_basic_rows]
    _check_unique(col_names, "combined column")
    _check_unique(row_names, "combined row")
    col_status = [*first.col_status, *second.col_status]
    row_status = [*first.row_status, *second.row_status, *([BASIC] * len(additional_basic_rows))]
    _validate_simplex_cardinality(col_status, row_status)
    return BasisVectors(col_names, row_names, col_status, row_status)


def reorder_basis_vectors(
    basis: BasisVectors,
    column_names: Sequence[str],
    row_names: Sequence[str],
) -> BasisVectors:
    """Reorder name-based statuses to the order used by a target model."""
    target_columns, target_rows = list(column_names), list(row_names)
    _check_unique(target_columns, "target column")
    _check_unique(target_rows, "target row")
    if set(basis.col_names) != set(target_columns):
        raise BasisFileError("Basis columns do not have the same names as the target model")
    if set(basis.row_names) != set(target_rows):
        raise BasisFileError("Basis rows do not have the same names as the target model")
    column_status = dict(zip(basis.col_names, basis.col_status))
    row_status = dict(zip(basis.row_names, basis.row_status))
    ordered = BasisVectors(
        target_columns,
        target_rows,
        [column_status[name] for name in target_columns],
        [row_status[name] for name in target_rows],
    )
    _validate_simplex_cardinality(ordered.col_status, ordered.row_status)
    return ordered


def read_highs_basis_file(path) -> BasisVectors:
    with open_text_read(path) as f:
        lines = [line.rstrip("\n") for line in f]
    if not lines or not lines[0].strip().startswith("HiGHS_basis_file"):
        raise BasisFileError(f"{path}: not a HiGHS_basis_file")
    i = 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        raise BasisFileError(f"{path}: truncated HiGHS basis file")
    if lines[i].strip().lower() != "valid":
        raise BasisFileError(f"{path}: HiGHS basis is not marked Valid (got {lines[i]!r})")
    i += 1

    def read_section(marker):
        nonlocal i
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines) or not lines[i].strip().startswith(marker):
            raise BasisFileError(f"{path}: expected {marker} section")
        try:
            count = int(lines[i].strip().split()[-1])
        except Exception as exc:
            raise BasisFileError(f"{path}: invalid section count in {lines[i]!r}") from exc
        i += 1
        names, statuses = [], []
        for _ in range(count):
            if i >= len(lines):
                raise BasisFileError(f"{path}: truncated {marker} section")
            text = lines[i].strip(); i += 1
            try:
                name, status_text = text.rsplit(None, 1)
                native = int(status_text)
            except Exception as exc:
                raise BasisFileError(f"{path}: invalid entity/status line {text!r}") from exc
            if native not in HIGHS_INT_TO_STATUS:
                raise BasisFileError(f"{path}: unknown HiGHS basis status integer {native} for {name!r}")
            names.append(name); statuses.append(HIGHS_INT_TO_STATUS[native])
        return names, statuses

    col_names, col_status = read_section("# Columns")
    row_names, row_status = read_section("# Rows")
    return BasisVectors(col_names, row_names, col_status, row_status)


def convert_highs_basis_file_to_mps_bas(input_path, output_path, *, expected_col_names=None, expected_row_names=None, problem_name="HIGHSBAS") -> None:
    basis = read_highs_basis_file(input_path)
    if expected_col_names is not None and list(expected_col_names) != basis.col_names:
        raise BasisFileError("HiGHS basis column names/order do not match the loaded model")
    if expected_row_names is not None and list(expected_row_names) != basis.row_names:
        raise BasisFileError("HiGHS basis row names/order do not match the loaded model")
    write_mps_bas(output_path, basis.col_names, basis.row_names, basis.col_status, basis.row_status, problem_name=problem_name)


def _main():
    import argparse
    parser = argparse.ArgumentParser(description="Basis-file compatibility helpers")
    sub = parser.add_subparsers(dest="command", required=True)
    conv = sub.add_parser("highs-to-bas", help="Convert HiGHS_basis_file text to classical MPS BAS")
    conv.add_argument("input_basis")
    conv.add_argument("output_bas")
    conv.add_argument("--name", default="HIGHSBAS")
    args = parser.parse_args()
    if args.command == "highs-to-bas":
        convert_highs_basis_file_to_mps_bas(args.input_basis, args.output_bas, problem_name=args.name)
        print(args.output_bas)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
