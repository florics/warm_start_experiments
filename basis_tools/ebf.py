#!/usr/bin/env python3
"""Explicit Basis Format (EBF), format version 1.1.

Variables:
    var_name,basis_status,bound_status,value
Constraints:
    constr_name,basis_status,bound_status,activity

The implementation is solver-independent. Solver translation belongs in the
shared solver adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence
import csv
import math

from .io_utils import open_text_read, open_text_write

FORMAT_NAME = "Explicit Basis Format"
FORMAT_ABBREVIATION = "EBF"
FORMAT_VERSION = "1.1"
VARIABLE_COLUMNS = ("var_name", "basis_status", "bound_status", "value")
CONSTRAINT_COLUMNS = ("constr_name", "basis_status", "bound_status", "activity")


class BasisStatus(str, Enum):
    BASIC = "BASIC"
    NONBASIC = "NONBASIC"
    SUPERBASIC = "SUPERBASIC"


class BoundStatus(str, Enum):
    LOWER = "LOWER"
    UPPER = "UPPER"
    FIXED = "FIXED"
    INTERIOR = "INTERIOR"
    FREE = "FREE"


@dataclass(frozen=True)
class VariableBasisEntry:
    var_name: str
    basis_status: BasisStatus
    bound_status: BoundStatus
    value: Optional[float]


@dataclass(frozen=True)
class ConstraintBasisEntry:
    constr_name: str
    basis_status: BasisStatus
    bound_status: BoundStatus
    activity: Optional[float]


@dataclass(frozen=True)
class EBFFileComparison:
    entity_type: str
    num_rows: int
    basis_status_differences: int
    bound_status_differences: int
    numerical_field: str
    numerical_tolerance: float
    numerical_comparable_rows: int
    numerical_missing_mismatches: int
    numerical_difference_rows: Optional[int]
    max_abs_numerical_difference: Optional[float]


@dataclass(frozen=True)
class EBFBasisComparison:
    variables: EBFFileComparison
    constraints: EBFFileComparison


class EBFError(ValueError):
    pass


class EBFSchemaError(EBFError):
    pass


class EBFValidationError(EBFError):
    pass


def get_format_name() -> str:
    return FORMAT_NAME


def get_format_abbreviation() -> str:
    return FORMAT_ABBREVIATION


def get_format_version() -> str:
    return FORMAT_VERSION


def get_format_info() -> dict[str, str]:
    return {"name": FORMAT_NAME, "abbreviation": FORMAT_ABBREVIATION, "version": FORMAT_VERSION}


def classify_bound_status(lower: float, upper: float, value: float, *, tolerance: float = 1e-9) -> BoundStatus:
    if tolerance < 0:
        raise ValueError("tolerance must be nonnegative")
    lower_finite = math.isfinite(lower)
    upper_finite = math.isfinite(upper)
    if lower_finite and upper_finite and abs(upper - lower) <= tolerance:
        return BoundStatus.FIXED
    if not lower_finite and not upper_finite:
        return BoundStatus.FREE
    if lower_finite and abs(value - lower) <= tolerance:
        return BoundStatus.LOWER
    if upper_finite and abs(value - upper) <= tolerance:
        return BoundStatus.UPPER
    return BoundStatus.INTERIOR


def validate_status_pair(basis_status: BasisStatus, bound_status: BoundStatus, *, entity_name: str = "") -> None:
    if basis_status == BasisStatus.BASIC:
        return
    if basis_status == BasisStatus.NONBASIC and bound_status in {BoundStatus.LOWER, BoundStatus.UPPER, BoundStatus.FIXED}:
        return
    if basis_status == BasisStatus.SUPERBASIC and bound_status in {BoundStatus.INTERIOR, BoundStatus.FREE}:
        return
    prefix = f"{entity_name}: " if entity_name else ""
    raise EBFValidationError(f"{prefix}invalid status combination ({basis_status.value}, {bound_status.value})")


def validate_variable_entries(entries: Sequence[VariableBasisEntry]) -> None:
    seen: set[str] = set()
    for entry in entries:
        if not entry.var_name:
            raise EBFValidationError("Variable name must not be empty")
        if entry.var_name in seen:
            raise EBFValidationError(f"Duplicate variable entry: {entry.var_name}")
        seen.add(entry.var_name)
        validate_status_pair(entry.basis_status, entry.bound_status, entity_name=f"variable {entry.var_name}")


def validate_constraint_entries(entries: Sequence[ConstraintBasisEntry]) -> None:
    seen: set[str] = set()
    for entry in entries:
        if not entry.constr_name:
            raise EBFValidationError("Constraint name must not be empty")
        if entry.constr_name in seen:
            raise EBFValidationError(f"Duplicate constraint entry: {entry.constr_name}")
        seen.add(entry.constr_name)
        validate_status_pair(entry.basis_status, entry.bound_status, entity_name=f"constraint {entry.constr_name}")


def _parse_optional_float(text: str, *, field: str, row_number: int) -> Optional[float]:
    text = text.strip()
    if text == "":
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise EBFSchemaError(f"Row {row_number}: {field} must be a float or empty, got {text!r}") from exc
    if math.isnan(value):
        raise EBFSchemaError(f"Row {row_number}: {field} must not be NaN")
    return value


def _parse_basis_status(text: str, row_number: int) -> BasisStatus:
    try:
        return BasisStatus(text.strip())
    except ValueError as exc:
        raise EBFSchemaError(f"Row {row_number}: invalid basis_status {text!r}") from exc


def _parse_bound_status(text: str, row_number: int) -> BoundStatus:
    try:
        return BoundStatus(text.strip())
    except ValueError as exc:
        raise EBFSchemaError(f"Row {row_number}: invalid bound_status {text!r}") from exc


def read_variable_basis_csv(path: str | Path, *, validate: bool = True) -> list[VariableBasisEntry]:
    with open_text_read(path) as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise EBFSchemaError(f"{path}: CSV has no header")
        if tuple(reader.fieldnames) != VARIABLE_COLUMNS:
            raise EBFSchemaError(f"{path}: expected columns {VARIABLE_COLUMNS}, got {tuple(reader.fieldnames)}")
        entries = [
            VariableBasisEntry(
                var_name=(row["var_name"] or "").strip(),
                basis_status=_parse_basis_status(row["basis_status"] or "", n),
                bound_status=_parse_bound_status(row["bound_status"] or "", n),
                value=_parse_optional_float(row["value"] or "", field="value", row_number=n),
            )
            for n, row in enumerate(reader, start=2)
        ]
    if validate:
        validate_variable_entries(entries)
    return entries


def read_constraint_basis_csv(path: str | Path, *, validate: bool = True) -> list[ConstraintBasisEntry]:
    with open_text_read(path) as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise EBFSchemaError(f"{path}: CSV has no header")
        if tuple(reader.fieldnames) != CONSTRAINT_COLUMNS:
            raise EBFSchemaError(f"{path}: expected columns {CONSTRAINT_COLUMNS}, got {tuple(reader.fieldnames)}")
        entries = [
            ConstraintBasisEntry(
                constr_name=(row["constr_name"] or "").strip(),
                basis_status=_parse_basis_status(row["basis_status"] or "", n),
                bound_status=_parse_bound_status(row["bound_status"] or "", n),
                activity=_parse_optional_float(row["activity"] or "", field="activity", row_number=n),
            )
            for n, row in enumerate(reader, start=2)
        ]
    if validate:
        validate_constraint_entries(entries)
    return entries


def _format_optional_float(value: Optional[float]) -> str:
    return "" if value is None else repr(float(value))


def write_variable_basis_csv(path: str | Path, entries: Sequence[VariableBasisEntry], *, validate: bool = True) -> None:
    if validate:
        validate_variable_entries(entries)
    ordered = sorted(entries, key=lambda entry: entry.var_name)
    with open_text_write(path) as file:
        writer = csv.writer(file)
        writer.writerow(VARIABLE_COLUMNS)
        for entry in ordered:
            writer.writerow([entry.var_name, entry.basis_status.value, entry.bound_status.value, _format_optional_float(entry.value)])


def write_constraint_basis_csv(path: str | Path, entries: Sequence[ConstraintBasisEntry], *, validate: bool = True) -> None:
    if validate:
        validate_constraint_entries(entries)
    ordered = sorted(entries, key=lambda entry: entry.constr_name)
    with open_text_write(path) as file:
        writer = csv.writer(file)
        writer.writerow(CONSTRAINT_COLUMNS)
        for entry in ordered:
            writer.writerow([entry.constr_name, entry.basis_status.value, entry.bound_status.value, _format_optional_float(entry.activity)])


def is_degenerate_status(basis_status: BasisStatus, bound_status: BoundStatus) -> bool:
    return basis_status == BasisStatus.BASIC and bound_status in {BoundStatus.LOWER, BoundStatus.UPPER, BoundStatus.FIXED}


def count_basic_entries(variable_entries, constraint_entries) -> int:
    return sum(e.basis_status == BasisStatus.BASIC for e in variable_entries) + sum(e.basis_status == BasisStatus.BASIC for e in constraint_entries)


def count_superbasic_entries(variable_entries, constraint_entries) -> int:
    return sum(e.basis_status == BasisStatus.SUPERBASIC for e in variable_entries) + sum(e.basis_status == BasisStatus.SUPERBASIC for e in constraint_entries)


def validate_simplex_basis(variable_entries, constraint_entries, *, num_rows: int) -> None:
    validate_variable_entries(variable_entries)
    validate_constraint_entries(constraint_entries)
    num_basic = count_basic_entries(variable_entries, constraint_entries)
    num_superbasic = count_superbasic_entries(variable_entries, constraint_entries)
    errors = []
    if num_basic != num_rows:
        errors.append(f"BASIC entries={num_basic}, expected num_rows={num_rows}")
    if num_superbasic:
        errors.append(f"SUPERBASIC entries={num_superbasic}, expected 0")
    if errors:
        raise EBFValidationError("Invalid simplex basis: " + "; ".join(errors))


def get_basic_entity_ids(variable_entries, constraint_entries) -> set[str]:
    result = {f"VAR:{e.var_name}" for e in variable_entries if e.basis_status == BasisStatus.BASIC}
    result.update(f"ROW:{e.constr_name}" for e in constraint_entries if e.basis_status == BasisStatus.BASIC)
    return result


def basis_exchange_distance(vars_a, constrs_a, vars_b, constrs_b) -> int:
    a = get_basic_entity_ids(vars_a, constrs_a)
    b = get_basic_entity_ids(vars_b, constrs_b)
    if len(a) != len(b):
        raise EBFValidationError(f"Cannot compute exchange distance for basis sets of different sizes: {len(a)} vs {len(b)}")
    symmetric = len(a.symmetric_difference(b))
    if symmetric % 2:
        raise EBFValidationError("Basic-set symmetric difference has odd size")
    return symmetric // 2


def _compare_entry_lists(entries_a, entries_b, *, name_attr, numerical_attr, entity_type, numerical_tolerance):
    if numerical_tolerance < 0:
        raise ValueError("numerical_tolerance must be nonnegative")
    map_a = {getattr(e, name_attr): e for e in entries_a}
    map_b = {getattr(e, name_attr): e for e in entries_b}
    names_a, names_b = set(map_a), set(map_b)
    if names_a != names_b:
        only_a = sorted(names_a - names_b)
        only_b = sorted(names_b - names_a)
        raise EBFSchemaError(
            f"{entity_type} names differ. Only in first={only_a[:10]}{'...' if len(only_a)>10 else ''}; "
            f"only in second={only_b[:10]}{'...' if len(only_b)>10 else ''}."
        )
    names = sorted(names_a)
    basis_diffs = sum(map_a[n].basis_status != map_b[n].basis_status for n in names)
    bound_diffs = sum(map_a[n].bound_status != map_b[n].bound_status for n in names)
    comparable = missing_mismatches = numerical_diffs = 0
    max_abs_diff: Optional[float] = None
    if basis_diffs == 0:
        for name in names:
            a = getattr(map_a[name], numerical_attr)
            b = getattr(map_b[name], numerical_attr)
            if a is None and b is None:
                continue
            if (a is None) != (b is None):
                missing_mismatches += 1
                numerical_diffs += 1
                continue
            assert a is not None and b is not None
            comparable += 1
            diff = abs(a - b)
            max_abs_diff = diff if max_abs_diff is None else max(max_abs_diff, diff)
            if diff > numerical_tolerance:
                numerical_diffs += 1
    return EBFFileComparison(
        entity_type, len(names), basis_diffs, bound_diffs, numerical_attr,
        numerical_tolerance, comparable, missing_mismatches,
        None if basis_diffs else numerical_diffs,
        None if basis_diffs else max_abs_diff,
    )


def _read_header(path):
    with open_text_read(path) as f:
        try:
            return tuple(next(csv.reader(f)))
        except StopIteration as exc:
            raise EBFSchemaError(f"Empty EBF file: {path}") from exc


def compare_ebf_files(first, second, *, numerical_tolerance: float = 0.0, print_result: bool = True) -> EBFFileComparison:
    h1, h2 = _read_header(first), _read_header(second)
    if h1 != h2:
        raise EBFSchemaError(f"Files have different headers: {h1} vs {h2}")
    if h1 == VARIABLE_COLUMNS:
        result = _compare_entry_lists(read_variable_basis_csv(first), read_variable_basis_csv(second), name_attr="var_name", numerical_attr="value", entity_type="variables", numerical_tolerance=numerical_tolerance)
    elif h1 == CONSTRAINT_COLUMNS:
        result = _compare_entry_lists(read_constraint_basis_csv(first), read_constraint_basis_csv(second), name_attr="constr_name", numerical_attr="activity", entity_type="constraints", numerical_tolerance=numerical_tolerance)
    else:
        raise EBFSchemaError(f"Not an EBF 1.1 CSV header: {h1}")
    if print_result:
        print(format_comparison(result))
    return result


def compare_ebf_bases(vars_a, constrs_a, vars_b, constrs_b, *, numerical_tolerance: float = 0.0, print_result: bool = True) -> EBFBasisComparison:
    variables = compare_ebf_files(vars_a, vars_b, numerical_tolerance=numerical_tolerance, print_result=False)
    constraints = compare_ebf_files(constrs_a, constrs_b, numerical_tolerance=numerical_tolerance, print_result=False)
    result = EBFBasisComparison(variables, constraints)
    if print_result:
        print(format_comparison(variables))
        print(format_comparison(constraints))
    return result


def format_comparison(result: EBFFileComparison) -> str:
    lines = [
        f"EBF comparison ({result.entity_type}, {result.num_rows} rows)",
        f"basis_status differing rows: {result.basis_status_differences}",
        f"bound_status differing rows: {result.bound_status_differences}",
    ]
    if result.basis_status_differences == 0:
        max_diff = "n/a" if result.max_abs_numerical_difference is None else repr(result.max_abs_numerical_difference)
        lines.extend([
            f"max absolute {result.numerical_field} difference: {max_diff}",
            f"rows with {result.numerical_field} difference > {result.numerical_tolerance}: {result.numerical_difference_rows}",
            f"rows with comparable numerical values: {result.numerical_comparable_rows}",
            f"rows with one numerical value missing: {result.numerical_missing_mismatches}",
        ])
    return "\n".join(lines)
