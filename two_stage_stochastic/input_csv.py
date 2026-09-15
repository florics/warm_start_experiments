"""Input handling shared by the two-stage experiment drivers."""
from __future__ import annotations

import csv
from pathlib import Path


INPUT_COLUMNS = (
    "integrated_lp", "first_lp", "first_bas", "first_scenarioname",
    "second_lp", "second_bas", "second_scenarioname",
)
MULTI_INPUT_COLUMNS = ("integrated_lp", "lp", "bas", "scenarioname")


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


def read_multi_input_csv(path: Path) -> tuple[Path, list[tuple[str, Path, Path]]]:
    """Read a multi-scenario CSV with one source LP/BAS pair per row."""
    path = Path(path).expanduser().resolve()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or set(MULTI_INPUT_COLUMNS) - set(reader.fieldnames):
            raise ValueError(f"{path}: required columns are {', '.join(MULTI_INPUT_COLUMNS)}")
        rows = list(reader)
    if len(rows) < 2:
        raise ValueError(f"{path}: expected at least two data rows, found {len(rows)}")
    scenarios = []
    integrated_paths = set()
    for row in rows:
        values = {column: (row.get(column) or "").strip() for column in MULTI_INPUT_COLUMNS}
        missing = [column for column, value in values.items() if not value]
        if missing:
            raise ValueError(f"{path}: empty {missing[0]!r}")
        integrated = (path.parent / values["integrated_lp"]).resolve() if not Path(values["integrated_lp"]).is_absolute() else Path(values["integrated_lp"])
        lp = (path.parent / values["lp"]).resolve() if not Path(values["lp"]).is_absolute() else Path(values["lp"])
        bas = (path.parent / values["bas"]).resolve() if not Path(values["bas"]).is_absolute() else Path(values["bas"])
        integrated_paths.add(integrated)
        scenarios.append((values["scenarioname"], lp, bas))
    if len(integrated_paths) != 1:
        raise ValueError(f"{path}: integrated_lp must be identical in every row")
    return integrated_paths.pop(), scenarios


def apply_input_csv(args, parser) -> None:
    positional = (args.first_lp, args.first_bas, args.second_lp, args.second_bas, args.integrated_lp)
    if args.input_csv:
        if any(path is not None for path in positional) or args.scenario:
            parser.error("--input-csv cannot be combined with positional paths or --scenario")
        try:
            with Path(args.input_csv).open(newline="", encoding="utf-8") as handle:
                columns = set(csv.DictReader(handle).fieldnames or [])
            if set(MULTI_INPUT_COLUMNS).issubset(columns):
                args.integrated_lp, args.scenarios = read_multi_input_csv(args.input_csv)
                if args.scenario_a or args.scenario_b:
                    parser.error("--scenario-a/--scenario-b are only supported with the legacy two-scenario CSV")
                return
            row = read_input_csv(args.input_csv)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        args.first_lp, args.first_bas = row["first_lp"], row["first_bas"]
        args.second_lp, args.second_bas = row["second_lp"], row["second_bas"]
        args.integrated_lp = row["integrated_lp"]
        args.scenario_a = args.scenario_a or row["first_scenarioname"]
        args.scenario_b = args.scenario_b or row["second_scenarioname"]
    elif args.scenario:
        if any(path is not None for path in positional):
            parser.error("--scenario cannot be combined with positional LP/BAS paths")
        if args.integrated_lp_option is None:
            parser.error("--scenario requires --integrated-lp")
        if args.scenario_a or args.scenario_b:
            parser.error("--scenario cannot be combined with --scenario-a/--scenario-b")
        args.integrated_lp = args.integrated_lp_option
        args.scenarios = [(name, Path(lp), Path(bas)) for name, lp, bas in args.scenario]
        if len(args.scenarios) < 2:
            parser.error("--scenario must be supplied at least twice")
        return
    elif any(path is None for path in positional):
        parser.error("provide all positional LP/BAS paths or --input-csv")
    if not args.scenario_a or not args.scenario_b:
        parser.error("provide --scenario-a/--scenario-b or scenario names in --input-csv")
    args.scenarios = [
        (args.scenario_a, args.first_lp, args.first_bas),
        (args.scenario_b, args.second_lp, args.second_bas),
    ]
