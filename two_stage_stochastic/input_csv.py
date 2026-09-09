"""One-row input CSV handling shared by two-stage experiment drivers."""
from __future__ import annotations

import csv
from pathlib import Path


INPUT_COLUMNS = (
    "integrated_lp", "first_lp", "first_bas", "first_scenarioname",
    "second_lp", "second_bas", "second_scenarioname",
)


def read_input_csv(path: Path) -> dict[str, str | Path]:
    path = Path(path).expanduser().resolve()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or set(INPUT_COLUMNS) - set(reader.fieldnames):
            raise ValueError(f"{path}: required columns are {', '.join(INPUT_COLUMNS)}")
        rows = list(reader)
    if len(rows) != 1:
        raise ValueError(f"{path}: expected exactly one data row, found {len(rows)}")
    row = rows[0]
    result: dict[str, str | Path] = {}
    for column in INPUT_COLUMNS:
        value = (row.get(column) or "").strip()
        if not value:
            raise ValueError(f"{path}: empty {column!r}")
        result[column] = (path.parent / value).resolve() if column.endswith(("_lp", "_bas")) and not Path(value).is_absolute() else Path(value) if column.endswith(("_lp", "_bas")) else value
    return result


def apply_input_csv(args, parser) -> None:
    positional = (args.first_lp, args.first_bas, args.second_lp, args.second_bas, args.integrated_lp)
    if args.input_csv:
        if any(path is not None for path in positional):
            parser.error("--input-csv cannot be combined with positional LP/BAS paths")
        try:
            row = read_input_csv(args.input_csv)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        args.first_lp, args.first_bas = row["first_lp"], row["first_bas"]
        args.second_lp, args.second_bas = row["second_lp"], row["second_bas"]
        args.integrated_lp = row["integrated_lp"]
        args.scenario_a = args.scenario_a or row["first_scenarioname"]
        args.scenario_b = args.scenario_b or row["second_scenarioname"]
    elif any(path is None for path in positional):
        parser.error("provide all positional LP/BAS paths or --input-csv")
    if not args.scenario_a or not args.scenario_b:
        parser.error("provide --scenario-a/--scenario-b or scenario names in --input-csv")
