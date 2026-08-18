#!/usr/bin/env python3
"""Generate solver bases for every LP × solver-parameter configuration.

For each solve, store EBF 1.1 and, if the EBF is a proper simplex basis, a
classical .bas file. HiGHS writes its native basis temporarily and converts it
through basis_tools.mps_bas before the final .bas is stored.
"""
from __future__ import annotations

import argparse
import csv
import os
import platform
import shutil
import socket
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0,str(PROJECT_ROOT))

from basis_tools.basis_export import export_ebf
from basis_tools.ebf import EBFValidationError, get_format_info
from basis_tools.io_utils import has_logical_suffix, output_path
from basis_tools.solver_adapters import get_solver_adapter

INSTANCE_COLUMNS=["name","lp_file"]
PARAMETER_COLUMNS=["solver","parameter_name","parameter_file"]
SUMMARY_COLUMNS=["timestamp","instance_name","lp_file","solver","solver_version","parameter_name","parameter_file","copied_parameter_file","log_file","basis_file","ebf_vars_file","ebf_constrs_file","ebf_format_version","bound_tolerance","status","status_code","objective_value","solve_time_s","external_wallclock_s","simplex_iterations","barrier_iterations","work_units","result","message"]


def now_stamp(): return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
def sanitize(text):
    value="".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(text)).strip("_"); return value or "unnamed"

def create_unique_run_dir(base_dir):
    base_dir=Path(base_dir).expanduser().resolve(); base_dir.mkdir(parents=True,exist_ok=True)
    while True:
        out=base_dir/f"run_{now_stamp()}"
        if out.exists(): print(f"{out} already exists; waiting one second."); time.sleep(1); continue
        out.mkdir(); return out

def resolve_relative(path_text,parent):
    p=Path(path_text).expanduser(); return (p if p.is_absolute() else parent/p).resolve()

def read_instances(path):
    path=Path(path).expanduser().resolve()
    if not path.is_file(): raise FileNotFoundError(f"Instances CSV not found: {path}")
    rows=[]
    with path.open("r",newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames is None: raise ValueError("Instances CSV has no header.")
        missing=[c for c in INSTANCE_COLUMNS if c not in reader.fieldnames]
        if missing: raise ValueError(f"Instances CSV missing columns: {missing}")
        for lineno,row in enumerate(reader,start=2):
            name=(row.get("name") or "").strip(); lp_text=(row.get("lp_file") or "").strip()
            if not name or not lp_text: raise ValueError(f"{path}:{lineno}: name and lp_file must be nonempty.")
            lp_file=resolve_relative(lp_text,path.parent)
            if not lp_file.is_file(): raise FileNotFoundError(f"{path}:{lineno}: LP file not found: {lp_file}")
            if not has_logical_suffix(lp_file,".lp"): raise ValueError(f"{path}:{lineno}: expected .lp, .lp.gz or .lp.zip file: {lp_file}")
            rows.append({"name":name,"lp_file":lp_file})
    if not rows: raise ValueError("Instances CSV contains no instances.")
    names=[r["name"] for r in rows]; dup=sorted({n for n in names if names.count(n)>1})
    if dup: raise ValueError(f"Duplicate instance names: {dup}")
    return rows

def read_solver_parameters(path):
    path=Path(path).expanduser().resolve()
    if not path.is_file(): raise FileNotFoundError(f"Solver-parameters CSV not found: {path}")
    rows=[]; supported={"gurobi","copt","highs","xpress"}
    with path.open("r",newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames is None: raise ValueError("Solver-parameters CSV has no header.")
        missing=[c for c in PARAMETER_COLUMNS if c not in reader.fieldnames]
        if missing: raise ValueError(f"Solver-parameters CSV missing columns: {missing}")
        for lineno,row in enumerate(reader,start=2):
            solver=(row.get("solver") or "").strip().lower(); parameter_name=(row.get("parameter_name") or "").strip(); parameter_text=(row.get("parameter_file") or "").strip()
            if solver not in supported: raise ValueError(f"{path}:{lineno}: unsupported solver {solver!r}; expected one of {sorted(supported)}")
            if not parameter_name or not parameter_text: raise ValueError(f"{path}:{lineno}: parameter_name and parameter_file must be nonempty.")
            parameter_file=resolve_relative(parameter_text,path.parent)
            if not parameter_file.is_file(): raise FileNotFoundError(f"{path}:{lineno}: parameter file not found: {parameter_file}")
            rows.append({"solver":solver,"parameter_name":parameter_name,"parameter_file":parameter_file})
    if not rows: raise ValueError("Solver-parameters CSV contains no configurations.")
    keys=[(r["solver"],r["parameter_name"]) for r in rows]; dup=sorted({k for k in keys if keys.count(k)>1})
    if dup: raise ValueError(f"parameter_name must be unique within each solver. Duplicate keys: {dup}")
    return rows

def initialize_summary(path):
    with path.open("w",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=SUMMARY_COLUMNS).writeheader()
def append_summary(path,row):
    with path.open("a",newline="",encoding="utf-8") as f:
        csv.DictWriter(f,fieldnames=SUMMARY_COLUMNS).writerow({k:row.get(k,"") for k in SUMMARY_COLUMNS}); f.flush()
        try: os.fsync(f.fileno())
        except OSError: pass

def copy_parameter_file(config,run_dir):
    target_dir=run_dir/"parameters"/config["solver"]; target_dir.mkdir(parents=True,exist_ok=True); source=config["parameter_file"]; suffix="".join(source.suffixes) or ".txt"; target=target_dir/f"{sanitize(config['parameter_name'])}{suffix}"; shutil.copy2(source,target); return target

def version_string(adapter):
    info=adapter.version_info(); return str(info.get("solver_version",info)) if isinstance(info,dict) else str(info)

def write_experiment_info(run_dir,instances_csv,parameters_csv,instances,configs,bound_tolerance,compress_output):
    path=run_dir/"experiment_info.txt"; fmt=get_format_info(); adapters={}
    for c in configs:
        if c["solver"] not in adapters:
            try: adapters[c["solver"]]=get_solver_adapter(c["solver"])
            except Exception as exc: adapters[c["solver"]]=exc
    with path.open("w",encoding="utf-8") as f:
        f.write("Solver basis generation experiment\n"+"="*80+"\n\n"); f.write(f"Created: {datetime.now().isoformat()}\nHostname: {socket.gethostname()}\nPlatform: {platform.platform()}\nPython: {sys.version}\nPython executable: {sys.executable}\nInstances CSV: {instances_csv}\nSolver parameters CSV: {parameters_csv}\nInstances: {len(instances)}\nSolver/parameter configurations: {len(configs)}\nPlanned solves: {len(instances)*len(configs)}\nCompressed output artifacts: {compress_output}\n")
        f.write("\nExplicit Basis Format\n"+"-"*80+"\n"); f.write(f"Format: {fmt['name']} ({fmt['abbreviation']}) {fmt['version']}\nImplementation module: basis_tools.ebf\nVariables: var_name,basis_status,bound_status,value\nConstraints: constr_name,basis_status,bound_status,activity\nbasis_status: BASIC, NONBASIC, SUPERBASIC\nbound_status: LOWER, UPPER, FIXED, INTERIOR, FREE\nBound classification tolerance: {bound_tolerance}\n")
        f.write("Constraint bound_status is derived from row activity and row bounds, never copied from solver-native row/slack status.\nA stored .bas is required to pass the EBF proper-simplex validation: BASIC count = number of rows and no SUPERBASIC.\nHiGHS .bas output is converted from temporary native HiGHS_basis_file text using basis_tools.mps_bas.\nLP/BAS/EBF input supports plain, .gz and single-file .zip; BAS/EBF output supports plain and .gz.\n")
        f.write("\nSolver versions / import status\n"+"-"*80+"\n")
        for solver,adapter in sorted(adapters.items()):
            if isinstance(adapter,Exception): f.write(f"{solver}: import failed: {adapter}\n")
            else:
                try: f.write(f"{solver}: {adapter.version_info()}\n")
                except Exception as exc: f.write(f"{solver}: version unavailable: {exc}\n")
        f.write("\nSLURM environment\n"+"-"*80+"\n")
        for key in ("SLURM_JOB_ID","SLURM_JOB_NAME","SLURM_JOB_NODELIST","SLURM_CPUS_PER_TASK","SLURM_CPUS_ON_NODE","SLURM_NTASKS","SLURM_CPU_FREQ_REQ"):
            if key in os.environ: f.write(f"{key}={os.environ[key]}\n")
    return path

def solve_one(instance,config,copied_parameter_file,run_dir,solver_version,*,bound_tolerance,compress_output):
    timestamp=now_stamp(); solver=config["solver"]; instance_safe=sanitize(instance["name"]); param_safe=sanitize(config["parameter_name"]); prefix=f"{instance_safe}__{solver}__{param_safe}__{timestamp}"
    log_dir=run_dir/"logs"/solver; basis_dir=run_dir/"bases"/solver/param_safe; ebf_dir=run_dir/"explicit_bases"/solver/param_safe
    for d in (log_dir,basis_dir,ebf_dir): d.mkdir(parents=True,exist_ok=True)
    log_file=log_dir/f"{prefix}.log"; basis_file=output_path(basis_dir/f"{instance_safe}.bas",compress=compress_output); ebf_vars_file=output_path(ebf_dir/f"{instance_safe}__vars.csv",compress=compress_output); ebf_constrs_file=output_path(ebf_dir/f"{instance_safe}__constrs.csv",compress=compress_output); fmt=get_format_info()
    result={"timestamp":timestamp,"instance_name":instance["name"],"lp_file":str(instance["lp_file"]),"solver":solver,"solver_version":solver_version,"parameter_name":config["parameter_name"],"parameter_file":str(config["parameter_file"]),"copied_parameter_file":str(copied_parameter_file),"log_file":str(log_file),"basis_file":"","ebf_vars_file":"","ebf_constrs_file":"","ebf_format_version":fmt["version"],"bound_tolerance":bound_tolerance,"status":"","status_code":"","objective_value":"","solve_time_s":"","external_wallclock_s":"","simplex_iterations":"","barrier_iterations":"","work_units":"","result":"ERROR","message":""}
    print("\n"+"="*100); print(f"Instance       : {instance['name']}\nLP             : {instance['lp_file']}\nSolver         : {solver}\nParameter set  : {config['parameter_name']}\nParameter file : {copied_parameter_file}\nBAS output     : {basis_file}\nEBF variables  : {ebf_vars_file}\nEBF constraints: {ebf_constrs_file}"); print("="*100)
    # HiGHS writes directly to stdout, so flush Python's run banner first.
    sys.stdout.flush()
    adapter=model=None
    try:
        adapter=get_solver_adapter(solver); model=adapter.load_model(instance["lp_file"]); adapter.read_parameters(model,copied_parameter_file); adapter.set_log_file(model,log_file)
        t0=time.time(); adapter.optimize(model); external=time.time()-t0; native=adapter.collect_result(model,external)
        result.update({"status":native.get("status",""),"status_code":native.get("status_code",""),"objective_value":native.get("objective_value",""),"solve_time_s":native.get("solve_time_s",""),"external_wallclock_s":external,"simplex_iterations":native.get("simplex_iterations",""),"barrier_iterations":native.get("barrier_iterations",""),"work_units":native.get("work_units","")})
        adapter.print_diagnostics(model)
        if not native.get("is_optimal",False): result["result"]="NONOPTIMAL"; result["message"]="Optimization did not terminate with an optimal LP solution; basis was not written."; return result
        try:
            export_ebf(adapter,model,ebf_vars_file,ebf_constrs_file,tolerance=bound_tolerance,validate=True,write_before_validation=True); result["ebf_vars_file"]=str(ebf_vars_file); result["ebf_constrs_file"]=str(ebf_constrs_file)
        except EBFValidationError as exc:
            result["ebf_vars_file"]=str(ebf_vars_file); result["ebf_constrs_file"]=str(ebf_constrs_file); result["result"]="INVALID_SIMPLEX_BASIS"; result["message"]=str(exc); return result
        try:
            adapter.write_basis(model,basis_file)
            if not basis_file.is_file():
                raise RuntimeError(f"Basis writer returned without creating {basis_file}")
        except Exception as exc:
            result["result"]="BASIS_WRITE_ERROR"
            result["message"]=(
                "EBF was written and validated, but the classical "
                f".bas basis could not be written: {exc}"
            )
            return result
        result["basis_file"]=str(basis_file); result["result"]="OK"; return result
    except Exception as exc:
        result["message"]=f"{exc}; traceback: {traceback.format_exc()}"; return result
    finally:
        if adapter is not None and model is not None:
            try: adapter.dispose(model)
            except Exception: pass

def parse_args():
    p=argparse.ArgumentParser(description="Generate .bas and EBF files for LPs using Gurobi, COPT, HiGHS and/or Xpress")
    p.add_argument("instances_csv"); p.add_argument("solver_parameters_csv"); p.add_argument("results_dir"); p.add_argument("--bound-tolerance",type=float,default=1e-9); p.add_argument("--compress-output",action=argparse.BooleanOptionalAction,default=True,help="Compress generated BAS/EBF files with gzip (default: enabled)."); return p.parse_args()

def main():
    args=parse_args()
    if args.bound_tolerance<0:
        print("PRECHECK FAILED: --bound-tolerance must be nonnegative.",file=sys.stderr)
        return 1

    instances_csv=Path(args.instances_csv).expanduser().resolve()
    parameters_csv=Path(args.solver_parameters_csv).expanduser().resolve()
    results_dir=Path(args.results_dir).expanduser().resolve()

    # Full preflight before creating a run directory, as in the previous
    # working generator.  In particular, fail immediately if any requested
    # solver adapter cannot be imported/initialized.
    try:
        instances=read_instances(instances_csv)
        configs=read_solver_parameters(parameters_csv)
        adapters={}
        for config in configs:
            solver=config["solver"]
            if solver not in adapters:
                adapters[solver]=get_solver_adapter(solver)
    except Exception as exc:
        print(f"PRECHECK FAILED: {exc}",file=sys.stderr)
        return 1

    run_dir=create_unique_run_dir(results_dir)
    for dirname in ("parameters","logs","bases","explicit_bases"):
        (run_dir/dirname).mkdir()

    shutil.copy2(instances_csv,run_dir/"input_instances.csv")
    shutil.copy2(parameters_csv,run_dir/"input_solver_parameters.csv")

    copied={}
    for config in configs:
        key=(config["solver"],config["parameter_name"])
        copied[key]=copy_parameter_file(config,run_dir)

    write_experiment_info(
        run_dir,instances_csv,parameters_csv,instances,configs,
        args.bound_tolerance,args.compress_output,
    )

    summary=run_dir/"summary.csv"
    initialize_summary(summary)

    solver_versions={}
    for solver,adapter in adapters.items():
        try:
            solver_versions[solver]=version_string(adapter)
        except Exception:
            solver_versions[solver]="unknown"

    total=len(instances)*len(configs)
    run_index=0
    failures=0

    for instance in instances:
        for config in configs:
            run_index+=1
            print(f"\nRUN {run_index}/{total}")
            key=(config["solver"],config["parameter_name"])
            row=solve_one(
                instance,config,copied[key],run_dir,
                solver_versions[config["solver"]],
                bound_tolerance=args.bound_tolerance,
                compress_output=args.compress_output,
            )
            append_summary(summary,row)
            if row["result"]!="OK":
                failures+=1
            print(
                f"Result={row['result']} | status={row['status']} | "
                f"bas={row['basis_file'] or 'NOT WRITTEN'} | "
                f"ebf_vars={row['ebf_vars_file'] or 'NOT WRITTEN'} | "
                f"ebf_constrs={row['ebf_constrs_file'] or 'NOT WRITTEN'}"
            )
            if row["message"]:
                print(f"Message: {row['message']}")
            sys.stdout.flush(); sys.stderr.flush()

    print("\n"+"="*100)
    print("BATCH FINISHED")
    print(f"Run directory : {run_dir}")
    print(f"Summary       : {summary}")
    print(f"Total runs    : {total}")
    print(f"Failures      : {failures}")
    print("="*100)
    return 0 if failures==0 else 2

if __name__=="__main__": raise SystemExit(main())
