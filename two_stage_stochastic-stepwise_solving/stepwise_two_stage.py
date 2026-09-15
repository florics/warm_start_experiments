#!/usr/bin/env python3
"""Incrementally add two-stage coupling rows to one live LP model."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from basis_tools.mps_bas import BASIC, BasisVectors, reorder_basis_vectors, write_mps_bas
from basis_tools.solver_adapters import SUPPORTED_SOLVERS, get_solver_adapter
from two_stage_stochastic.basis_merge import build_combined_basis, nonanticipativity_row_name, nonanticipativity_row_names, scenario_indexed_name
from two_stage_stochastic.construct_two_stage_basis import create_run_directory, investment_variables, require_same_structure, write_optimal_artifacts
from two_stage_stochastic.input_csv import apply_input_csv
from stepwise_core import Coupling, disagreement, rank_violations, violation_summary


STEP_COLUMNS = [
    "step", "strategy", "satisfied_rows_added", "selected_row", "first_variable", "second_variable",
    "first_value_before", "second_value_before", "absolute_disagreement", "relative_disagreement",
    "first_basic_before", "second_basic_before", "couplings_present", "couplings_remaining",
    "objective_before", "objective_after", "simplex_iterations", "runtime_s", "work_units",
    "cumulative_simplex_iterations", "cumulative_runtime_s", "became_satisfied", "violated_before",
    "max_relative_before", "mean_relative_before", "violated_after", "max_relative_after", "mean_relative_after",
]


def without_rows(basis: BasisVectors, rows: set[str]) -> BasisVectors:
    keep = [index for index, name in enumerate(basis.row_names) if name not in rows]
    return BasisVectors(list(basis.col_names), [basis.row_names[index] for index in keep], list(basis.col_status), [basis.row_status[index] for index in keep])


def write_steps(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=STEP_COLUMNS)
        writer.writeheader(); writer.writerows(rows)


def append_step(rows, *, step, strategy, satisfied, selected, basic, present, remaining, before, after, solve, cumulative_iterations, cumulative_runtime, became_satisfied, violations_before, violations_after):
    selected_data = selected or {}
    coupling = selected_data.get("coupling")
    rows.append({
        "step": step, "strategy": strategy, "satisfied_rows_added": json.dumps([item.row_name for item in satisfied]),
        "selected_row": coupling.row_name if coupling else "", "first_variable": coupling.first_name if coupling else "", "second_variable": coupling.second_name if coupling else "",
        "first_value_before": selected_data.get("first_value", ""), "second_value_before": selected_data.get("second_value", ""),
        "absolute_disagreement": selected_data.get("absolute", ""), "relative_disagreement": selected_data.get("relative", ""),
        "first_basic_before": basic[coupling.first_index] if coupling else "", "second_basic_before": basic[coupling.second_index] if coupling else "",
        "couplings_present": present, "couplings_remaining": remaining, "objective_before": before,
        "objective_after": after, "simplex_iterations": solve.get("simplex_iterations", 0), "runtime_s": solve.get("external_wallclock_s", 0.0),
        "work_units": solve.get("work_units", ""), "cumulative_simplex_iterations": cumulative_iterations,
        "cumulative_runtime_s": cumulative_runtime, "became_satisfied": became_satisfied,
        "violated_before": violation_summary(violations_before)["count"], "max_relative_before": violation_summary(violations_before)["max_relative"],
        "mean_relative_before": violation_summary(violations_before)["mean_relative"], "violated_after": violation_summary(violations_after)["count"],
        "max_relative_after": violation_summary(violations_after)["max_relative"], "mean_relative_after": violation_summary(violations_after)["mean_relative"],
    })


def solve_worker(config_path: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8")); adapter = get_solver_adapter(config["solver"]); model = None
    result = {"repetition": config["repetition"], "is_optimal": False, "solver_log": config["solver_log"], "steps_csv": config["steps_csv"]}
    try:
        model = adapter.load_model(Path(config["integrated_lp"])); adapter.read_parameters(model, Path(config["parameter_file"])); adapter.validate_loaded_parameters(model)
        adapter.set_log_file(model, Path(config["solver_log"])); adapter.remove_rows(model, config["coupling_rows"]); adapter.read_basis(model, Path(config["uncoupled_basis_file"]))
        tolerance = adapter.get_feasibility_tolerance(model); columns, _ = adapter.get_model_names(model); positions = {name: index for index, name in enumerate(columns)}
        couplings = [
            Coupling(
                item["row_name"], item["original_name"],
                scenario_indexed_name(item["original_name"], item["reference_scenario"]),
                scenario_indexed_name(item["original_name"], item["scenario"]),
                positions[scenario_indexed_name(item["original_name"], item["reference_scenario"])],
                positions[scenario_indexed_name(item["original_name"], item["scenario"])],
            )
            for item in config["couplings"]
        ]
        print(f"[PHASE] STEPWISE {config['repetition']}/{config['total_repetitions']}: solve uncoupled model once.", flush=True)
        start = time.perf_counter(); adapter.optimize(model); initial = adapter.collect_result(model, time.perf_counter() - start)
        if not initial.get("is_optimal"):
            result.update(initial); result["status"] = "UNCoupled_SOLVE_FAILED"; return 0
        rows = []; remaining = list(couplings); rng = random.Random(config["random_seed"]); cumulative_iterations = int(initial.get("simplex_iterations") or 0); cumulative_runtime = float(initial.get("external_wallclock_s") or 0.0); step = 0
        if config["strategy"] == "all_at_once":
            values, basic = adapter.get_column_values_and_basic(model); before = initial.get("objective_value")
            for coupling in remaining: adapter.add_equality_row(model, coupling.first_index, coupling.second_index, coupling.row_name)
            start = time.perf_counter(); solved = adapter.collect_result(model, time.perf_counter() - start) if not remaining else None
            if remaining:
                start = time.perf_counter(); adapter.optimize(model); solved = adapter.collect_result(model, time.perf_counter() - start)
            append_step(rows, step=1, strategy=config["strategy"], satisfied=[], selected=None, basic=basic, present=0, remaining=0, before=before, after=solved.get("objective_value"), solve=solved, cumulative_iterations=cumulative_iterations + int(solved.get("simplex_iterations") or 0), cumulative_runtime=cumulative_runtime + float(solved.get("external_wallclock_s") or 0.0), became_satisfied=0, violations_before=[], violations_after=[])
            remaining = [] ; final = solved
        else:
            final = initial
            while remaining:
                values, basic = adapter.get_column_values_and_basic(model); records = [disagreement(coupling, values, tolerance) for coupling in remaining]
                satisfied_records = [record for record in records if record["satisfied"]]; satisfied = [record["coupling"] for record in satisfied_records]
                for coupling in satisfied: adapter.add_equality_row(model, coupling.first_index, coupling.second_index, coupling.row_name)
                remaining = [coupling for coupling in remaining if coupling not in satisfied]
                violated = [record for record in records if not record["satisfied"]]
                if not remaining:
                    append_step(rows, step=step + 1, strategy=config["strategy"], satisfied=satisfied, selected=None, basic=basic, present=len(couplings), remaining=0, before=final.get("objective_value"), after=final.get("objective_value"), solve={}, cumulative_iterations=cumulative_iterations, cumulative_runtime=cumulative_runtime, became_satisfied=0, violations_before=violated, violations_after=[])
                    break
                selected = rank_violations(violated, config["strategy"], rng); coupling = selected["coupling"]; adapter.add_equality_row(model, coupling.first_index, coupling.second_index, coupling.row_name); remaining.remove(coupling)
                before = final.get("objective_value"); start = time.perf_counter(); final = adapter.optimize(model) or adapter.collect_result(model, time.perf_counter() - start)
                cumulative_iterations += int(final.get("simplex_iterations") or 0); cumulative_runtime += float(final.get("external_wallclock_s") or 0.0)
                after_values, _ = adapter.get_column_values_and_basic(model); after_violated = [disagreement(item, after_values, tolerance) for item in remaining if not disagreement(item, after_values, tolerance)["satisfied"]]
                became = len([record for record in violated if record["coupling"] in remaining and record["coupling"] not in [item["coupling"] for item in after_violated]])
                step += 1; append_step(rows, step=step, strategy=config["strategy"], satisfied=satisfied, selected=selected, basic=basic, present=len(couplings) - len(remaining), remaining=len(remaining), before=before, after=final.get("objective_value"), solve=final, cumulative_iterations=cumulative_iterations, cumulative_runtime=cumulative_runtime, became_satisfied=became, violations_before=violated, violations_after=after_violated)
        values, _ = adapter.get_column_values_and_basic(model); final_records = [disagreement(coupling, values, tolerance) for coupling in couplings]
        if config["write_artifacts"]:
            write_steps(Path(config["steps_csv"]), rows)
        result.update(final); result.update({"is_optimal": bool(final.get("is_optimal")), "all_couplings_added": not remaining, "final_violations": sum(not record["satisfied"] for record in final_records), "feasibility_tolerance": tolerance, "steps": len(rows)})
        if result["is_optimal"] and result["all_couplings_added"] and result["final_violations"] == 0:
            if config["write_artifacts"]:
                result.update(write_optimal_artifacts(adapter, model, Path(config["output_dir"]), config["solver"]))
        else: result["status"] = "FINAL_VALIDATION_FAILED"
    except Exception as error:
        result["status"] = "ERROR"; result["message"] = str(error)
    finally:
        if model is not None: adapter.dispose(model)
        Path(config["result_path"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker-config": return solve_worker(Path(sys.argv[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("solver", choices=SUPPORTED_SOLVERS); parser.add_argument("first_lp", type=Path, nargs="?"); parser.add_argument("first_bas", type=Path, nargs="?"); parser.add_argument("second_lp", type=Path, nargs="?"); parser.add_argument("second_bas", type=Path, nargs="?"); parser.add_argument("integrated_lp", type=Path, nargs="?")
    parser.add_argument("--input-csv", type=Path, help="CSV supplying source LPs, bases, and scenario names"); parser.add_argument("--scenario", action="append", nargs=3, metavar=("NAME", "LP", "BAS"), help="scenario identifier, source LP, and source BAS; repeat for each scenario"); parser.add_argument("--integrated-lp", dest="integrated_lp_option", type=Path, help="integrated LP used with repeated --scenario"); parser.add_argument("--output-parent", required=True, type=Path); parser.add_argument("--scenario-a"); parser.add_argument("--scenario-b"); parser.add_argument("--reference-scenario", help="scenario used on the +1 side of coupling rows (default: first scenario)"); parser.add_argument("--parameter-file", required=True, type=Path); parser.add_argument("--strategy", choices=("relative_ascending", "relative_descending", "random", "all_at_once"), default="relative_ascending"); parser.add_argument("--random-seed", type=int, default=0); parser.add_argument("--repetitions", type=int, default=1); parser.add_argument("--measure", action=argparse.BooleanOptionalAction, default=True); parser.add_argument("--write-artifacts", action=argparse.BooleanOptionalAction, default=False, help="write post-solve optimal basis, EBF, and solution artifacts"); parser.add_argument("--run-label")
    args = parser.parse_args()
    apply_input_csv(args, parser)
    if args.repetitions < 1: parser.error("--repetitions must be at least 1")
    adapter = get_solver_adapter(args.solver); source_models = []; integrated = None; reference_scenario = args.reference_scenario or args.scenarios[0][0]; output_dir = create_run_directory(args.output_parent, args.integrated_lp, args.solver, f"stepwise_{args.strategy}" + (f"_{args.run_label}" if args.run_label else "")); report = {"solver": args.solver, "strategy": args.strategy, "output_dir": str(output_dir), "integrated_lp": str(args.integrated_lp), "scenarios": [{"name": name, "lp": str(lp), "basis": str(bas)} for name, lp, bas in args.scenarios], "reference_scenario": reference_scenario, "write_artifacts": args.write_artifacts, "status": "ERROR"}
    try:
        source_descriptors = []; canonical_columns = canonical_rows = None
        for name, lp, bas in args.scenarios:
            model = adapter.load_model(lp); source_models.append(model); columns, rows = adapter.get_model_names(model)
            if canonical_columns is None: canonical_columns, canonical_rows = columns, rows
            else: require_same_structure(canonical_columns, canonical_rows, columns, rows)
            source_descriptors.append((name, bas, columns, rows))
        investments = investment_variables(canonical_columns)
        scenario_names = [name for name, _lp, _bas in args.scenarios]
        coupling_rows = nonanticipativity_row_names(investments, scenario_names, reference_scenario); combined = build_combined_basis(source_descriptors, investments, reference_scenario)
        coupling_specs = [
            {"row_name": nonanticipativity_row_name(variable, reference_scenario, scenario), "original_name": variable, "reference_scenario": reference_scenario, "scenario": scenario}
            for variable in investments for scenario in scenario_names if scenario != reference_scenario
        ]
        integrated = adapter.load_model(args.integrated_lp); adapter.remove_rows(integrated, coupling_rows); columns, rows = adapter.get_model_names(integrated); uncoupled = reorder_basis_vectors(without_rows(combined, set(coupling_rows)), columns, rows); uncoupled_basis = output_dir / "uncoupled_warmstart.bas.gz"; write_mps_bas(uncoupled_basis, uncoupled.col_names, uncoupled.row_names, uncoupled.col_status, uncoupled.row_status, problem_name="TWOSTAGE_STEPWISE")
        workers = output_dir / "workers"; workers.mkdir(); results = []
        for repetition in range(1, args.repetitions + 1):
            prefix = f"repetition_{repetition:03d}"; config = {"solver": args.solver, "repetition": repetition, "total_repetitions": args.repetitions, "integrated_lp": str(args.integrated_lp), "parameter_file": str(args.parameter_file), "uncoupled_basis_file": str(uncoupled_basis), "couplings": coupling_specs, "coupling_rows": coupling_rows, "strategy": args.strategy, "random_seed": args.random_seed, "write_artifacts": args.write_artifacts, "solver_log": str(output_dir / f"{prefix}.solver.log"), "steps_csv": str(output_dir / f"{prefix}.steps.csv"), "output_dir": str(output_dir), "config_path": str(workers / f"{prefix}.json"), "result_path": str(workers / f"{prefix}.result.json")}; Path(config["config_path"]).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
            command = [sys.executable, str(Path(__file__).resolve()), "--worker-config", config["config_path"]]
            if args.measure:
                if shutil.which("perf"):
                    command = ["/usr/bin/time", "-v", "perf", "stat", "-e", "cycles,instructions,task-clock,cpu-clock", "--", *command]
                else:
                    print("WARNING: perf is unavailable; collecting /usr/bin/time -v only.", file=sys.stderr)
                    command = ["/usr/bin/time", "-v", *command]
            print("Running:", " ".join(command), flush=True); completed = subprocess.run(command, stderr=sys.stdout); result_path = Path(config["result_path"]); result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {"status": "ERROR", "is_optimal": False, "message": "worker produced no result"}; result["measurement_exit_status"] = completed.returncode; results.append(result)
        status = "SOLVED" if all(result.get("is_optimal") and result.get("final_violations") == 0 for result in results) else "FAILED"
        if any(result.get("status") == "ERROR" and result.get("is_optimal") for result in results): status = "ARTIFACT_WRITE_ERROR"
        report.update({"status": status, "uncoupled_warmstart_basis": str(uncoupled_basis), "coupling_rows": len(coupling_rows), "repetitions": results})
    except Exception as error: report["message"] = str(error)
    finally:
        for model in (integrated, *source_models):
            if model is not None: adapter.dispose(model)
        (output_dir / "stepwise_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str)); return 0 if report["status"] == "SOLVED" else 2


if __name__ == "__main__": raise SystemExit(main())
