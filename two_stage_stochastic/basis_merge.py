#!/usr/bin/env python3
"""Construct a two-scenario BAS file from two scenario-specific BAS files."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Sequence

from basis_tools.mps_bas import (
    BasisFileError,
    BasisVectors,
    combine_basis_vectors,
    parse_mps_bas,
    rename_basis_vectors,
    write_mps_bas,
)


PAREN_IDENTIFIER_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\((?P<key>[^()\r\n]+)\)(?P<tail>_?)\Z"
)
BARE_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\Z")
SCENARIO_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


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


def _name_map(names: Sequence[str], scenario: str) -> dict[str, str]:
    mapped = {name: scenario_indexed_name(name, scenario) for name in names}
    if len(set(mapped.values())) != len(mapped):
        raise TwoStageBasisError(f"Scenario mapping produces duplicate names for scenario {scenario!r}")
    return mapped


def build_combined_basis(
    first_basis_path: Path,
    second_basis_path: Path,
    first_column_names: Sequence[str],
    first_row_names: Sequence[str],
    second_column_names: Sequence[str],
    second_row_names: Sequence[str],
    investment_variables: Sequence[str],
    first_scenario: str,
    second_scenario: str,
) -> BasisVectors:
    """Parse, rename, and block-combine scenario bases with BASIC coupling rows."""
    try:
        first = parse_mps_bas(first_basis_path, first_column_names, first_row_names)
        second = parse_mps_bas(second_basis_path, second_column_names, second_row_names)
        first = rename_basis_vectors(first, _name_map(first_column_names, first_scenario), _name_map(first_row_names, first_scenario))
        second = rename_basis_vectors(second, _name_map(second_column_names, second_scenario), _name_map(second_row_names, second_scenario))
        coupling_rows = [
            nonanticipativity_row_name(variable, first_scenario, second_scenario)
            for variable in investment_variables
        ]
        if len(set(coupling_rows)) != len(coupling_rows):
            raise TwoStageBasisError("Duplicate non-anticipativity row names")
        return combine_basis_vectors(first, second, coupling_rows)
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
