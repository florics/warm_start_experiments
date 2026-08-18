"""Shared EBF extraction, writing and proper-simplex validation."""
from __future__ import annotations
from pathlib import Path

from .ebf import validate_simplex_basis, write_constraint_basis_csv, write_variable_basis_csv
from .io_utils import output_path


def export_ebf(adapter, model, vars_path, constrs_path, *, tolerance=1e-9, validate=True, write_before_validation=False):
    variables, constraints = adapter.extract_ebf_entries(model, tolerance=tolerance)
    if write_before_validation:
        # Preserve diagnostic artifacts even when the subsequent validation fails.
        write_variable_basis_csv(vars_path, variables, validate=False)
        write_constraint_basis_csv(constrs_path, constraints, validate=False)
    if validate:
        validate_simplex_basis(variables, constraints, num_rows=adapter.get_num_rows(model))
    if not write_before_validation:
        write_variable_basis_csv(vars_path, variables)
        write_constraint_basis_csv(constrs_path, constraints)
    return variables, constraints


def ebf_output_paths(directory, prefix, *, compress=False):
    directory = Path(directory)
    return (
        output_path(directory / f"{prefix}__vars.csv", compress=compress),
        output_path(directory / f"{prefix}__constrs.csv", compress=compress),
    )
