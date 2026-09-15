#!/usr/bin/env python3
"""Construct a two-scenario BAS file from two scenario-specific BAS files."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Sequence

from basis_tools.mps_bas import (
    BASIC,
    BasisFileError,
    BasisVectors,
    parse_mps_bas,
    rename_basis_vectors,
    write_mps_bas,
)


PAREN_IDENTIFIER_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\((?P<key>[^()\r\n]+)\)(?P<tail>_?)\Z"
)
BARE_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\Z")
SCENARIO_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")


class TwoStageBasisError(ValueError):
    """A source basis or scenario-name mapping is incompatible."""


def scenario_indexed_name(name: str, scenario: str) -> str:
    """Apply the same scenario naming convention as the integrated LP writer."""
    if not SCENARIO_RE.fullmatch(scenario):
        raise TwoStageBasisError(f"Invalid scenario identifier: {scenario!r}")
    match = PAREN_IDENTIFIER_RE.fullmatch(name)
    if match is not None:
        return f"{match.group('name')}({match.group('key')}_{scenario}){match.group('tail')}"
    if not BARE_IDENTIFIER_RE.fullmatch(name):
        raise TwoStageBasisError(f"Unsupported LP identifier for scenario indexing: {name!r}")
    separator = "" if name.endswith("_") else "_"
    return f"{name}{separator}{scenario}_"


def nonanticipativity_row_name(variable_name: str, first_scenario: str, second_scenario: str) -> str:
    return f"c_e_nonanticipativity_({variable_name}_{first_scenario}_{second_scenario})_"


def nonanticipativity_row_names(investment_variables: Sequence[str], scenarios: Sequence[str], reference_scenario: str | None = None) -> list[str]:
    if len(scenarios) < 2:
        raise TwoStageBasisError("At least two scenarios are required")
    reference = reference_scenario or scenarios[0]
    if reference not in scenarios:
        raise TwoStageBasisError(f"Reference scenario is not an input scenario: {reference!r}")
    return [
        nonanticipativity_row_name(variable, reference, scenario)
        for variable in investment_variables
        for scenario in scenarios
        if scenario != reference
    ]


def _name_map(names: Sequence[str], scenario: str) -> dict[str, str]:
    mapped = {name: scenario_indexed_name(name, scenario) for name in names}
    if len(set(mapped.values())) != len(mapped):
        raise TwoStageBasisError(f"Scenario mapping produces duplicate names for scenario {scenario!r}")
    return mapped


def build_combined_basis(scenarios: Sequence[tuple[str, Path, Sequence[str], Sequence[str]]], investment_variables: Sequence[str], reference_scenario: str | None = None) -> BasisVectors:
    """Parse and combine scenario bases with BASIC reference-star coupling rows."""
    try:
        if len(scenarios) < 2:
            raise TwoStageBasisError("At least two scenarios are required")
        names = [name for name, _path, _columns, _rows in scenarios]
        if len(set(names)) != len(names):
            raise TwoStageBasisError("Scenario identifiers must be unique")
        bases = []
        for scenario, basis_path, columns, rows in scenarios:
            basis = parse_mps_bas(basis_path, columns, rows)
            bases.append(rename_basis_vectors(basis, _name_map(columns, scenario), _name_map(rows, scenario)))
        coupling_rows = nonanticipativity_row_names(investment_variables, names, reference_scenario)
        if len(set(coupling_rows)) != len(coupling_rows):
            raise TwoStageBasisError("Duplicate non-anticipativity row names")
        return BasisVectors(
            [name for basis in bases for name in basis.col_names],
            [name for basis in bases for name in basis.row_names] + coupling_rows,
            [status for basis in bases for status in basis.col_status],
            [status for basis in bases for status in basis.row_status] + [BASIC] * len(coupling_rows),
        )
    except BasisFileError as error:
        raise TwoStageBasisError(str(error)) from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Library-oriented BAS merger. Use the two-stage experiment driver "
            "to obtain validated source model names and investment variables."
        )
    )
    parser.parse_args()
    raise SystemExit("This module is invoked by the two-stage experiment driver, not directly.")


if __name__ == "__main__":
    main()
