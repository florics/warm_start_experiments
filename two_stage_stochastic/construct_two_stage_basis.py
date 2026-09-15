#!/usr/bin/env python3
"""Construct and validate a two-scenario warm-start BAS file.

The optional --solve path loads the resulting basis into the integrated model,
checks that every coupling row is BASIC, then optimizes using the supplied
external dual-simplex parameter file.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from basis_tools.mps_bas import BASIC, parse_mps_bas, reorder_basis_vectors, write_mps_bas
from basis_tools.basis_export import ebf_output_paths
from basis_tools.ebf import EBFValidationError, validate_simplex_basis, write_constraint_basis_csv, write_variable_basis_csv
from basis_tools.io_utils import logical_path
from basis_tools.solver_adapters import SUPPORTED_SOLVERS, get_solver_adapter
from two_stage_stochastic.basis_merge import (
    TwoStageBasisError,
    build_combined_basis,
    nonanticipativity_row_names,
)
from two_stage_stochastic.input_csv import apply_input_csv


INVESTMENT_PREFIXES = (
    "InvestmentFlowBlock_invest(",
    "InvestmentFlowBlock_total(",
    "GenericInvestmentStorageBlock_invest(",
    "GenericInvestmentStorageBlock_total(",
    "InvestmentFlowBlock_capacity(",
    "InvestmentFlowBlock_flowcapacity(",
    "GenericInvestmentStorageBlock_contentcapacity(",
)


def investment_variables(column_names: list[str]) -> list[str]:
    # The integrated LP writer emits coupling rows in lexicographic variable
    # order, so the BAS must use the same order.
    variables = sorted(name for name in column_names if name.startswith(INVESTMENT_PREFIXES))
    if not variables:
        raise TwoStageBasisError("No supported investment variables found in the first scenario model")
    return variables


def require_same_structure(first_columns, first_rows, second_columns, second_rows) -> None:
    if first_columns != second_columns or first_rows != second_rows:
        raise TwoStageBasisError("Scenario models do not have identical ordered column and row names")


def first_difference(expected: list[str], actual: list[str], kind: str) -> str:
    if len(expected) != len(actual):
        return f"{kind} count differs: expected {len(expected)}, actual {len(actual)}"
    for position, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            return f"first {kind} mismatch at index {position}: expected {left!r}, actual {right!r}"
    return f"{kind} lists differ for an unknown reason"


def initial_dual_feasibility_from_log(solver: str, log_path: Path) -> dict[str, object]:
    """Extract iteration-zero dual-feasibility evidence from a solver log."""
    if not log_path.is_file():
        return {"status": "NOT_REPORTED", "message": f"Solver log was not written: {log_path}"}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if solver == "gurobi":
        match = re.search(r"(?m)^\s*0\s+.*?\s+(?P<dual>[+-]?[0-9.]+(?:[eE][+-]?\d+)?)\s+\S+\s*$", text)
        if match:
            value = float(match.group("dual"))
            return {"status": "CONFIRMED", "initial_dual_infeasibility": value, "dual_feasible": value == 0.0, "evidence": match.group(0).strip()}
    elif solver == "copt":
        match = re.search(r"(?m)^\s*Dual\s+0\s+.*?\s+(?P<dual>\d+)\s+\S+s\s*$", text)
        if match:
            value = int(match.group("dual"))
            return {"status": "CONFIRMED", "initial_dual_infeasibilities": value, "dual_feasible": value == 0, "evidence": match.group(0).strip()}
    elif solver == "xpress":
        match = re.search(r"(?m)^\s*0\s+.*?\s+[DP]\s+\d+\s+\d+\s+(?P<dual>[0-9.]+)\s+\S+\s*$", text)
        if match:
            value = float(match.group("dual"))
            return {"status": "CONFIRMED", "initial_dual_infeasibility": value, "dual_feasible": value == 0.0, "evidence": match.group(0).strip()}
    elif solver == "highs":
        match = re.search(r"(?m)^Solving LP with useful basis so presolve not used$", text)
        if match:
            return {
                "status": "BASIS_ACCEPTED_NO_EXPLICIT_DUAL_METRIC",
                "dual_feasible": None,
                "evidence": match.group(0),
                "message": "HiGHS does not print an iteration-zero dual infeasibility count in this log format.",
            }
    return {"status": "NOT_REPORTED", "message": "Could not identify an iteration-zero dual-feasibility line in the solver log."}


def create_run_directory(output_parent: Path, integrated_lp: Path, solver: str, run_label: str | None) -> Path:
    output_parent.mkdir(parents=True, exist_ok=True)
    instance = re.sub(r"[^A-Za-z0-9._-]+", "_", logical_path(integrated_lp).stem).strip("._-")
    if not instance:
        raise ValueError(f"Could not derive a directory-safe instance name from {integrated_lp}")
    label = ""
    if run_label:
        label = re.sub(r"[^A-Za-z0-9._-]+", "_", run_label).strip("._-")
        if not label:
            raise ValueError("--run-label must contain at least one letter or number")
        label = f"_{label}"
    while True:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        directory = output_parent / f"run_{instance}_{solver}_{timestamp}{label}"
        try:
            directory.mkdir()
            return directory
        except FileExistsError:
            time.sleep(random.randint(1, 60))


def summarize_repetitions(results: list[dict[str, object]]) -> dict[str, object]:
    summary = {"requested": len(results), "optimal": sum(result["is_optimal"] for result in results)}
    for field in ("external_wallclock_s", "external_cpu_time_s", "solve_time_s", "simplex_iterations", "work_units"):
        values = [float(result[field]) for result in results if isinstance(result.get(field), (int, float))]
        if values:
            summary[field] = {"min": min(values), "median": statistics.median(values), "max": max(values)}
    return summary


def write_optimal_artifacts(adapter, model, output_dir: Path, solver: str) -> dict[str, object]:
    marker = output_dir / "optimal_artifacts.json"
    if marker.is_file():
        return json.loads(marker.read_text(encoding="utf-8"))
    optimal_bas = output_dir / "optimal_basis.bas.gz"
    optimal_ebf_vars, optimal_ebf_constraints = ebf_output_paths(output_dir, "optimal_basis", compress=True)
    optimal_solution = output_dir / ("optimal_solution.sol.zip" if solver == "xpress" else "optimal_solution.sol.gz")
    adapter.write_basis(model, optimal_bas)
    # Preserve raw native statuses even when strict EBF validation rejects a
    # numerically near-bound nonbasic row.
    variables, constraints = adapter.extract_ebf_entries(model, tolerance=0.0)
    validation_warning = None
    try:
        validate_simplex_basis(variables, constraints, num_rows=adapter.get_num_rows(model))
    except EBFValidationError as error:
        validation_warning = str(error)
        print(f"WARNING: EBF validation failed; writing unvalidated EBF files: {error}", flush=True)
    write_variable_basis_csv(optimal_ebf_vars, variables, validate=False)
    write_constraint_basis_csv(optimal_ebf_constraints, constraints, validate=False)
    adapter.write_solution(model, optimal_solution)
    artifacts = {
        "optimal_basis_file": str(optimal_bas),
        "optimal_ebf_variables_file": str(optimal_ebf_vars),
        "optimal_ebf_constraints_file": str(optimal_ebf_constraints),
        "optimal_solution_file": str(optimal_solution),
    }
    if validation_warning:
        artifacts["ebf_validation_warning"] = validation_warning
    marker.write_text(json.dumps(artifacts, indent=2) + "\n", encoding="utf-8")
    return artifacts


def run_worker(config_path: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    adapter = get_solver_adapter(config["solver"])
    model = None
    result = {"repetition": config["repetition"], "solver_log": config["solver_log"], "is_optimal": False}
    try:
        print(f"[PHASE] REPETITION {config['repetition']}/{config['total_repetitions']}: fresh integrated model and warm-start BAS.", flush=True)
        print(f"[INPUT] Integrated two-stage LP: {config['integrated_lp']}", flush=True)
        model = adapter.load_model(Path(config["integrated_lp"]))
        adapter.read_parameters(model, Path(config["parameter_file"]))
        adapter.validate_loaded_parameters(model)
        adapter.set_log_file(model, Path(config["solver_log"]))
        adapter.read_basis(model, Path(config["warmstart_basis_file"]))
        _, loaded_rows = adapter.get_basic_membership(model)
        missing = [name for name in config["coupling_rows"] if not loaded_rows.get(name, False)]
        if missing:
            raise TwoStageBasisError(f"Solver loaded the BAS but coupling rows are not BASIC: {missing[:3]}")
        initial_probe = None
        if config["check_initial_dual_feasibility"] and config["solver"] == "highs":
            print("[PHASE] INITIAL_DUAL_FEASIBILITY_PROBE_BEGIN: presolve=off; simplex_iteration_limit=0.", flush=True)
            initial_probe = adapter.probe_initial_dual_feasibility(model)
            print(f"[PHASE] INITIAL_DUAL_FEASIBILITY_PROBE_RESULT: {initial_probe}", flush=True)
            adapter.read_basis(model, Path(config["warmstart_basis_file"]))
            _, loaded_rows = adapter.get_basic_membership(model)
            missing = [name for name in config["coupling_rows"] if not loaded_rows.get(name, False)]
            if missing:
                raise TwoStageBasisError(f"HiGHS did not restore BASIC coupling rows after the probe: {missing[:3]}")
        elif config["check_initial_dual_feasibility"]:
            print("[PHASE] INITIAL_DUAL_FEASIBILITY_EVIDENCE: extracting iteration-zero log evidence.", flush=True)
        print("[PHASE] INTEGRATED_WARMSTART_SOLVE: optimizing the reloaded BAS with the supplied parameter file.", flush=True)
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        adapter.optimize(model)
        result.update(adapter.collect_result(model, time.perf_counter() - wall_start, time.process_time() - cpu_start))
        adapter.print_postsolve_information(model, result["external_wallclock_s"], result["external_cpu_time_s"])
        result["initial_dual_feasibility"] = (
            initial_probe or initial_dual_feasibility_from_log(config["solver"], Path(config["solver_log"]))
            if config["check_initial_dual_feasibility"] else {"status": "DISABLED"}
        )
        if config["write_artifacts"] and result["is_optimal"]:
            print("[PHASE] OPTIMAL_ARTIFACTS: writing only if this is the first optimal repetition.", flush=True)
            result.update(write_optimal_artifacts(adapter, model, Path(config["output_dir"]), config["solver"]))
    except Exception as error:
        result["status"] = "ERROR"
        result["message"] = str(error)
    finally:
        if model is not None:
            adapter.dispose(model)
        Path(config["result_path"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return 0


def run_measured_worker(config: dict[str, object]) -> dict[str, object]:
    config_path = Path(config["config_path"])
    result_path = Path(config["result_path"])
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    command = ["/usr/bin/time", "-v"]
    if shutil.which("perf"):
        command.extend(["perf", "stat", "-e", "cycles,instructions,task-clock,cpu-clock", "--"])
    else:
        print("WARNING: perf is unavailable; collecting /usr/bin/time -v only.", file=sys.stderr)
    command.extend([sys.executable, str(Path(__file__).resolve()), "--worker-config", str(config_path)])
    print("Measuring complete repetition with: " + " ".join(command), flush=True)
    completed = subprocess.run(command, stderr=sys.stdout)
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = {"repetition": config["repetition"], "solver_log": config["solver_log"], "is_optimal": False, "status": "ERROR", "message": "Measured worker produced no result file"}
    if completed.returncode:
        result["status"] = "ERROR"
        result["message"] = f"{result.get('message', '')}; /usr/bin/time or perf worker exited with status {completed.returncode}".strip("; ")
    return result


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker-config":
        return run_worker(Path(sys.argv[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("solver", choices=SUPPORTED_SOLVERS)
    parser.add_argument("first_lp", type=Path, nargs="?")
    parser.add_argument("first_bas", type=Path, nargs="?")
    parser.add_argument("second_lp", type=Path, nargs="?")
    parser.add_argument("second_bas", type=Path, nargs="?")
    parser.add_argument("integrated_lp", type=Path, nargs="?")
    parser.add_argument("--input-csv", type=Path, help="one-row CSV supplying LPs, bases, and scenario names")
    parser.add_argument("--scenario", action="append", nargs=3, metavar=("NAME", "LP", "BAS"), help="scenario identifier, source LP, and source BAS; repeat for each scenario")
    parser.add_argument("--integrated-lp", dest="integrated_lp_option", type=Path, help="integrated LP used with repeated --scenario")
    parser.add_argument("--output-parent", type=Path, required=True, help="parent directory for the timestamped run directory")
    parser.add_argument("--run-label", help="optional descriptive suffix for the timestamped run directory")
    parser.add_argument("--scenario-a")
    parser.add_argument("--scenario-b")
    parser.add_argument("--reference-scenario", help="scenario used on the +1 side of coupling rows (default: first scenario)")
    parser.add_argument("--parameter-file", type=Path)
    parser.add_argument("--solve", action="store_true")
    parser.add_argument("--repetitions", type=int, default=1, help="number of fresh integrated warm-start solves")
    parser.add_argument("--measure", action=argparse.BooleanOptionalAction, default=True, help="measure each repetition with /usr/bin/time -v and perf stat")
    parser.add_argument("--write-artifacts", action=argparse.BooleanOptionalAction, default=False, help="write post-solve optimal basis, EBF, and solution artifacts")
    parser.add_argument("--check-initial-dual-feasibility", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    apply_input_csv(args, parser)
    if args.solve and args.parameter_file is None:
        parser.error("--solve requires --parameter-file")
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")

    adapter = get_solver_adapter(args.solver)
    source_models = []
    integrated_model = None
    reference_scenario = args.reference_scenario or args.scenarios[0][0]
    output_dir = create_run_directory(args.output_parent, args.integrated_lp, args.solver, args.run_label)
    output_bas = output_dir / "integrated_warmstart.bas.gz"
    report_path = output_dir / "integrated_warmstart_report.json"
    report = {
        "solver": args.solver,
        "status": "ERROR",
        "output_dir": str(output_dir),
        "scenarios": [{"name": name, "lp": str(lp), "basis": str(bas)} for name, lp, bas in args.scenarios],
        "reference_scenario": reference_scenario,
        "write_artifacts": args.write_artifacts,
        "measured_trial_scope": "fresh worker process; LP/parameter/basis setup; solve; result collection; disposal",
        "integrated_lp": str(args.integrated_lp),
        "warmstart_basis_file": str(output_bas),
    }
    if len(args.scenarios) == 2:
        report.update({"first_lp": str(args.scenarios[0][1]), "second_lp": str(args.scenarios[1][1])})
    try:
        for name, lp, _bas in args.scenarios:
            print(f"[INPUT] Scenario {name} LP: {lp}", flush=True)
        print(f"[INPUT] Integrated two-stage LP: {args.integrated_lp}", flush=True)
        source_descriptors = []
        canonical_columns = canonical_rows = None
        for name, lp, bas in args.scenarios:
            model = adapter.load_model(lp)
            source_models.append(model)
            columns, rows = adapter.get_model_names(model)
            if canonical_columns is None:
                canonical_columns, canonical_rows = columns, rows
            else:
                require_same_structure(canonical_columns, canonical_rows, columns, rows)
            source_descriptors.append((name, bas, columns, rows))
        investments = investment_variables(canonical_columns)
        combined = build_combined_basis(source_descriptors, investments, reference_scenario)
        integrated_model = adapter.load_model(args.integrated_lp)
        integrated_columns, integrated_rows = adapter.get_model_names(integrated_model)
        try:
            combined = reorder_basis_vectors(combined, integrated_columns, integrated_rows)
        except ValueError as error:
            raise TwoStageBasisError(
                "Combined BAS names do not match the integrated LP: " + str(error)
            ) from error
        coupling_rows = nonanticipativity_row_names(investments, [name for name, _lp, _bas in args.scenarios], reference_scenario)
        write_mps_bas(output_bas, combined.col_names, combined.row_names, combined.col_status, combined.row_status, problem_name="TWOSTAGE")
        parsed = parse_mps_bas(output_bas, integrated_columns, integrated_rows)
        row_status = dict(zip(parsed.row_names, parsed.row_status))
        if any(row_status[name] != BASIC for name in coupling_rows):
            raise TwoStageBasisError("At least one coupling row is not BASIC in the written BAS")
        report.update({"status": "BAS_VALID", "investment_variables": len(investments), "coupling_rows": len(coupling_rows)})
        if args.solve:
            # Workers own fresh solver processes, so release the models used to
            # inspect names and build the shared warm-start BAS first.
            for model in (integrated_model, *source_models):
                adapter.dispose(model)
            integrated_model = None
            source_models = []
            worker_dir = output_dir / "workers"
            worker_dir.mkdir()
            repetition_results = []
            for repetition in range(1, args.repetitions + 1):
                solver_log = output_dir / f"integrated_warmstart_repetition_{repetition:03d}.solver.log"
                prefix = f"repetition_{repetition:03d}"
                config = {
                    "config_path": str(worker_dir / f"{prefix}.json"),
                    "result_path": str(worker_dir / f"{prefix}.result.json"),
                    "solver": args.solver,
                    "repetition": repetition,
                    "total_repetitions": args.repetitions,
                    "integrated_lp": str(args.integrated_lp),
                    "parameter_file": str(args.parameter_file),
                    "warmstart_basis_file": str(output_bas),
                    "coupling_rows": coupling_rows,
                    "check_initial_dual_feasibility": args.check_initial_dual_feasibility,
                    "write_artifacts": args.write_artifacts,
                    "solver_log": str(solver_log),
                    "output_dir": str(output_dir),
                }
                if args.measure:
                    result = run_measured_worker(config)
                else:
                    config_path = Path(config["config_path"])
                    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
                    run_worker(config_path)
                    result = json.loads(Path(config["result_path"]).read_text(encoding="utf-8"))
                repetition_results.append(result)
                if result.get("is_optimal") and "optimal_basis_file" not in report:
                    report.update({key: result[key] for key in ("optimal_basis_file", "optimal_ebf_variables_file", "optimal_ebf_constraints_file", "optimal_solution_file") if key in result})
            report["repetitions"] = repetition_results
            report["repetition_summary"] = summarize_repetitions(repetition_results)
            if any(result.get("status") == "ERROR" and result.get("is_optimal") for result in repetition_results):
                report["status"] = "ARTIFACT_WRITE_ERROR"
            elif all(result["is_optimal"] for result in repetition_results):
                report["status"] = "SOLVED"
            elif any(result["is_optimal"] for result in repetition_results):
                report["status"] = "PARTIALLY_SOLVED"
            else:
                report["status"] = "SOLVE_FAILED"
        print(json.dumps(report, indent=2, default=str))
        print(f"Output directory: {output_dir}")
        return 0
    except Exception as error:
        if report.get("status") == "SOLVED":
            report["status"] = "ARTIFACT_WRITE_ERROR"
        report["message"] = str(error)
        print(json.dumps(report, indent=2, default=str), file=sys.stderr)
        return 2
    finally:
        report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        for model in (integrated_model, *source_models):
            if model is not None:
                adapter.dispose(model)


if __name__ == "__main__":
    raise SystemExit(main())
