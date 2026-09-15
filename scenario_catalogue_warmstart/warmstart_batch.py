#!/usr/bin/env python3
"""Multi-solver dual-simplex warm-start benchmark.

Supported solvers: Gurobi, COPT, HiGHS, Xpress.
Uses the shared EBF 1.1 / BAS / solver-adapter implementation in basis_tools.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import csv
import json
import os
import platform
import random
import shutil
import socket
import subprocess
import sys
import time
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from basis_tools.basis_export import ebf_output_paths, export_ebf
from basis_tools.ebf import get_format_info
from basis_tools.io_utils import has_logical_suffix, output_path
from basis_tools.solver_adapters import get_solver_adapter

REQUIRED_DATA_COLUMNS = ["name", "lp_file", "basis_file", "basis_description"]
REQUIRED_EXPERIMENT_COLUMNS = ["instance_name", "basis_name"]
DETAILED_SUMMARY_COLUMNS = [
    "timestamp", "solver", "repetition", "problem_name", "lp_file",
    "warmstart_source_name", "warmstart_basis_description", "warmstart_basis_file",
    "parameter_file", "log_file", "optimal_basis_file", "ebf_vars_csv",
    "ebf_constrs_csv", "solver_status", "status_code", "objective_value",
    "solve_time_s", "external_wallclock_s", "external_cpu_time_s", "simplex_iterations", "work_units",
    "message",
]
SHORT_SUMMARY_COLUMNS = [
    "timestamp", "solver", "repetition", "problem_name", "warmstart_source_name",
    "warmstart_basis_description", "solver_status", "solve_time_s", "external_wallclock_s", "external_cpu_time_s",
    "simplex_iterations", "work_units",
]


def timestamp_now(): return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def create_unique_experiment_dir(base_results_dir: Path):
    base=Path(base_results_dir).expanduser().resolve(); base.mkdir(parents=True,exist_ok=True)
    while True:
        path=base/f"run_{timestamp_now()}"
        if path.exists():
            delay=random.randint(1,60)
            print(f"Experiment directory already exists: {path}\nWaiting {delay} seconds before trying again.")
            time.sleep(delay)
            continue
        try:
            path.mkdir()
        except FileExistsError:
            delay=random.randint(1,60)
            print(f"Experiment directory was created by another job: {path}\nWaiting {delay} seconds before trying again.")
            time.sleep(delay)
            continue
        return path


def sanitize_filename(text):
    safe="".join(c if c.isalnum() or c in "-_." else "_" for c in str(text)).strip("_"); return safe or "unnamed"


def append_message(current,new):
    if not new: return current
    return str(new) if not current else f"{current} ; {new}"


def resolve_relative_to(path_text,parent_dir):
    path=Path(path_text).expanduser()
    if not path.is_absolute(): path=parent_dir/path
    return path.resolve()


def initialize_csv(path,columns):
    with Path(path).open("w",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=columns).writeheader()


def append_csv_row(path,columns,row):
    with Path(path).open("a",newline="",encoding="utf-8") as f:
        csv.DictWriter(f,fieldnames=columns,extrasaction="ignore").writerow({c:row.get(c,"") for c in columns}); f.flush()
        try: os.fsync(f.fileno())
        except OSError: pass


def read_data_csv(csv_path):
    csv_path=Path(csv_path).expanduser().resolve()
    if not csv_path.is_file(): raise FileNotFoundError(f"Data CSV not found: {csv_path}")
    datasets=[]
    with csv_path.open("r",newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames is None: raise ValueError("Input data CSV has no header")
        missing=[c for c in REQUIRED_DATA_COLUMNS if c not in reader.fieldnames]
        if missing: raise ValueError("Input data CSV is missing: "+", ".join(missing))
        for n,row in enumerate(reader,start=2):
            name=(row.get("name") or "").strip(); lp=(row.get("lp_file") or "").strip(); basis=(row.get("basis_file") or "").strip(); desc=(row.get("basis_description") or "").strip()
            if not name or not lp or not basis: raise ValueError(f"Row {n}: name, lp_file and basis_file must be nonempty")
            datasets.append({"name":name,"lp_file":resolve_relative_to(lp,csv_path.parent),"basis_file":resolve_relative_to(basis,csv_path.parent),"basis_description":desc})
    if not datasets: raise ValueError("Input data CSV contains no datasets")
    names=[d["name"] for d in datasets]; dup=sorted({n for n in names if names.count(n)>1})
    if dup: raise ValueError("Dataset names must be unique; duplicates: "+", ".join(dup))
    return datasets


def check_dataset_files(datasets):
    errors=[]
    for d in datasets:
        if not d["lp_file"].is_file(): errors.append(f"LP does not exist for {d['name']}: {d['lp_file']}")
        if not d["basis_file"].is_file(): errors.append(f"Basis does not exist for {d['name']}: {d['basis_file']}")
        if d["lp_file"].exists() and not has_logical_suffix(d["lp_file"],".lp"): errors.append(f"LP must end .lp, .lp.gz or .lp.zip: {d['lp_file']}")
        if d["basis_file"].exists() and not has_logical_suffix(d["basis_file"],".bas"): errors.append(f"Basis must end .bas, .bas.gz or .bas.zip: {d['basis_file']}")
    if errors: raise ValueError("Input validation failed:\n  - "+"\n  - ".join(errors))


def read_experiments_csv(path,dataset_lookup):
    path=Path(path).expanduser().resolve()
    if not path.is_file(): raise FileNotFoundError(f"Experiments CSV not found: {path}")
    result=[]; seen=set()
    with path.open("r",newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames is None: raise ValueError("Experiments CSV has no header")
        missing=[c for c in REQUIRED_EXPERIMENT_COLUMNS if c not in reader.fieldnames]
        if missing: raise ValueError("Experiments CSV is missing: "+", ".join(missing))
        for n,row in enumerate(reader,start=2):
            a=(row.get("instance_name") or "").strip(); b=(row.get("basis_name") or "").strip()
            if a not in dataset_lookup: raise ValueError(f"Row {n}: unknown instance_name {a!r}")
            if b not in dataset_lookup: raise ValueError(f"Row {n}: unknown basis_name {b!r}")
            if a==b: raise ValueError(f"Row {n}: self warm-start {a!r} is not allowed")
            if (a,b) in seen: raise ValueError(f"Row {n}: duplicate experiment ({a}, {b})")
            seen.add((a,b)); result.append((dataset_lookup[a],dataset_lookup[b]))
    if not result: raise ValueError("Experiments CSV contains no experiments")
    return result


def build_all_experiments(datasets): return [(a,b) for a in datasets for b in datasets if a["name"]!=b["name"]]


def write_selected_experiments_csv(path,experiments):
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["instance_name","basis_name"])
        for a,b in experiments: w.writerow([a["name"],b["name"]])


def write_ebf_files(adapter,model,output_dir,prefix,tolerance,compress_output):
    vars_path,constrs_path=ebf_output_paths(output_dir,prefix,compress=compress_output)
    export_ebf(adapter,model,vars_path,constrs_path,tolerance=tolerance,validate=True,write_before_validation=True)
    return vars_path,constrs_path


def write_experiment_info(path,adapter,args,data_csv,experiments_csv,copied_param,effective_param,datasets,experiments,validated):
    version=adapter.version_info(); fmt=get_format_info(); slurm=["SLURM_JOB_ID","SLURM_JOB_NAME","SLURM_NODELIST","SLURM_CPUS_PER_TASK","SLURM_NTASKS","SLURM_MEM_PER_NODE","SLURM_CPU_FREQ_REQ"]
    with Path(path).open("w",encoding="utf-8") as f:
        f.write("Dual-simplex warm-start batch experiment\n"+"="*80+"\n\n")
        f.write(f"Created: {datetime.now().isoformat()}\nSolver key: {adapter.name}\nSolver: {version.get('solver')}\nSolver version: {version.get('solver_version')}\nPython API: {version.get('python_api')}\nPython API version: {version.get('python_api_version')}\nPython executable: {sys.executable}\nPython version: {sys.version}\nHostname: {socket.gethostname()}\nPlatform: {platform.platform()}\n")
        f.write("\nInput and experiment selection\n"+"-"*80+"\n")
        f.write(f"Data CSV: {data_csv}\nExperiments CSV: {experiments_csv if experiments_csv else 'not used'}\nSelection mode: {'all ordered combinations' if args.all_experiments else 'explicit subset'}\nRepetitions: {args.repetitions}\nDatasets: {len(datasets)}\nSelected experiments: {len(experiments)}\nPlanned solves: {len(experiments)*args.repetitions}\nCopied parameters: {copied_param}\nEffective parameters: {effective_param}\nValidated settings: {validated}\nWrite post-solve artifacts: {args.write_artifacts}\nSolve-only timer scope: adapter.optimize()\nEnd-to-end trial scope: fresh worker process; LP/options/basis setup; solve; result collection; disposal\nEBF bound tolerance: {args.bound_tolerance}\nCompressed output artifacts: {args.compress_output}\nPer-trial measurement: /usr/bin/time -v perf stat -e cycles,instructions,task-clock,cpu-clock\nMeasurement output: standard error redirected to standard output (the batch/SLURM .out log)\n")
        f.write("\nEBF\n"+"-"*80+"\n")
        f.write(f"Format: {fmt['name']} ({fmt['abbreviation']}) {fmt['version']}\nImplementation module: basis_tools.ebf\nVariable columns: var_name,basis_status,bound_status,value\nConstraint columns: constr_name,basis_status,bound_status,activity\nbasis_status: BASIC, NONBASIC, SUPERBASIC\nbound_status: LOWER, UPPER, FIXED, INTERIOR, FREE\n")
        f.write("Constraint bound_status is derived from row activity and row bounds, not native row/slack status.\n")
        f.write("LP/BAS/EBF input supports plain, .gz and single-file .zip; generated BAS/EBF can be gzip-compressed.\n")
        if adapter.name=="highs": f.write("HiGHS basis input: native HiGHS_basis_file or classical MPS BAS. HiGHS standard output: classical MPS BAS.\n")
        f.write("\nSLURM environment\n"+"-"*80+"\n")
        for key in slurm: f.write(f"{key}: {os.environ.get(key,'')}\n")
        f.write("\nDatasets\n"+"-"*80+"\n")
        for d in datasets: f.write(f"{d['name']}\n  LP: {d['lp_file']}\n  Basis: {d['basis_file']}\n  Description: {d['basis_description']}\n")
        f.write("\nSelected experiments\n"+"-"*80+"\n")
        for i,(a,b) in enumerate(experiments,1): f.write(f"{i}: {a['name']} <- basis from {b['name']}\n")


def blank_result(adapter,target,source,repetition,param_file,log_file):
    return {"timestamp":timestamp_now(),"solver":adapter.name,"repetition":repetition,"problem_name":target["name"],"lp_file":str(target["lp_file"]),"warmstart_source_name":source["name"],"warmstart_basis_description":source["basis_description"],"warmstart_basis_file":str(source["basis_file"]),"parameter_file":str(param_file),"log_file":str(log_file),"optimal_basis_file":"","ebf_vars_csv":"","ebf_constrs_csv":"","solver_status":"ERROR","status_code":"","objective_value":"","solve_time_s":"","external_wallclock_s":"","external_cpu_time_s":"","simplex_iterations":"","work_units":"","message":"","is_optimal":False}


def solve_one_warmstart(adapter,target,source,repetition,param_file,log_dir,basis_dir,ebf_dir,bound_tolerance,compress_output,write_artifacts,run_index,total_runs,experiment_index,total_experiments,total_repetitions):
    stamp=timestamp_now(); prefix=f"{sanitize_filename(target['name'])}__warm_from__{sanitize_filename(source['name'])}__rep_{repetition:03d}__{stamp}"
    log_file=Path(log_dir)/f"{prefix}.{adapter.name}.log"; row=blank_result(adapter,target,source,repetition,param_file,log_file); model=None
    print("\n"+"="*100); print(f"RUN {run_index} / {total_runs}\nEXPERIMENT {experiment_index} / {total_experiments}"); print("="*100)
    print(f"Solver                    : {adapter.name}\nTarget problem            : {target['name']}\nTarget LP                 : {target['lp_file']}\nWarm-start source         : {source['name']}\nWarm-start basis          : {source['basis_file']}\nBasis description         : {source['basis_description']}\nRepetition                : {repetition} / {total_repetitions}\nSolver log                : {log_file}")
    print("="*100+"\n")
    try:
        print(f"Reading LP from disk:\n  {target['lp_file']}"); sys.stdout.flush(); model=adapter.load_model(target["lp_file"])
        print(f"Reading parameter/options file:\n  {param_file}"); sys.stdout.flush(); adapter.read_parameters(model,param_file); adapter.validate_loaded_parameters(model); adapter.set_log_file(model,log_file); adapter.print_model_information(model)
        print(f"Reading warm-start basis from disk:\n  {source['basis_file']}")
        sys.stdout.flush()
        try: adapter.read_basis(model,source["basis_file"])
        except Exception as exc:
            row["solver_status"]="BASIS_READ_ERROR"; row["message"]=f"Failed to read warm-start basis: {exc}. Optimization was NOT started."; print("ERROR: warm-start basis could not be loaded.\n"+row["message"]); return row
        print("Warm-start basis loaded successfully.\nStarting optimization..."); sys.stdout.flush()
        wall_start=time.perf_counter(); cpu_start=time.process_time(); adapter.optimize(model); wall=time.perf_counter()-wall_start; cpu=time.process_time()-cpu_start
        result=adapter.collect_result(model,wall,cpu); adapter.print_postsolve_information(model,wall,cpu); sys.stdout.flush()
        row.update({"solver_status":result.get("status",""),"status_code":result.get("status_code",""),"objective_value":result.get("objective_value",""),"solve_time_s":result.get("solve_time_s",""),"external_wallclock_s":result.get("external_wallclock_s",wall),"external_cpu_time_s":result.get("external_cpu_time_s",cpu),"simplex_iterations":result.get("simplex_iterations",""),"work_units":result.get("work_units","")}); row["is_optimal"]=bool(result.get("is_optimal",False))
        if write_artifacts and repetition==1 and row["is_optimal"]:
            if not adapter.has_basis(model): row["message"]=append_message(row["message"],"Optimal solve produced no valid basis; basis/EBF output skipped")
            else:
                out_basis=output_path(Path(basis_dir)/f"{sanitize_filename(target['name'])}__warm_from__{sanitize_filename(source['name'])}.bas",compress=compress_output)
                try: adapter.write_basis(model,out_basis); row["optimal_basis_file"]=str(out_basis); print(f"Wrote output basis:\n  {out_basis}")
                except Exception as exc: row["message"]=append_message(row["message"],f"basis write failed: {exc}"); print(f"WARNING: basis write failed: {exc}")
                try:
                    ebf_prefix=f"{sanitize_filename(target['name'])}__warm_from__{sanitize_filename(source['name'])}"; vars_path,constrs_path=write_ebf_files(adapter,model,ebf_dir,ebf_prefix,bound_tolerance,compress_output); row["ebf_vars_csv"],row["ebf_constrs_csv"]=str(vars_path),str(constrs_path); print(f"Wrote EBF 1.1 files:\n  {vars_path}\n  {constrs_path}")
                except Exception as exc:
                    vars_path,constrs_path=ebf_output_paths(ebf_dir,ebf_prefix,compress=compress_output); row["ebf_vars_csv"],row["ebf_constrs_csv"]=str(vars_path),str(constrs_path)
                    row["message"]=append_message(row["message"],f"EBF validation failed; diagnostic EBF files were retained: {exc}"); print(f"WARNING: EBF validation failed; diagnostic EBF files were retained: {exc}")
        return row
    except Exception as exc:
        row["solver_status"]="ERROR"; row["message"]=append_message(row["message"],f"Fatal error: {exc}; traceback: {traceback.format_exc()}"); print(f"ERROR: {exc}"); return row
    finally:
        if model is not None: adapter.dispose(model)


def dataset_from_worker_config(data):
    return {"name":data["name"],"lp_file":Path(data["lp_file"]),"basis_file":Path(data["basis_file"]),"basis_description":data["basis_description"]}


def run_worker(config_path):
    with Path(config_path).open("r",encoding="utf-8") as f: config=json.load(f)
    adapter=get_solver_adapter(config["solver"])
    row=solve_one_warmstart(adapter,dataset_from_worker_config(config["target"]),dataset_from_worker_config(config["source"]),config["repetition"],Path(config["param_file"]),Path(config["log_dir"]),Path(config["basis_dir"]),Path(config["ebf_dir"]),config["bound_tolerance"],config["compress_output"],config["write_artifacts"],config["run_index"],config["total_runs"],config["experiment_index"],config["total_experiments"],config["total_repetitions"])
    with Path(config["result_path"]).open("w",encoding="utf-8") as f: json.dump(row,f,default=str)
    return 0


def run_measured_trial(adapter,target,source,repetition,param_file,log_dir,basis_dir,ebf_dir,bound_tolerance,compress_output,write_artifacts,run_index,total_runs,experiment_index,total_experiments,total_repetitions,worker_dir):
    prefix=f"{sanitize_filename(target['name'])}__warm_from__{sanitize_filename(source['name'])}__rep_{repetition:03d}__{timestamp_now()}"
    config_path=Path(worker_dir)/f"{prefix}.json"; result_path=Path(worker_dir)/f"{prefix}.result.json"
    config={"solver":adapter.name,"target":{k:str(v) if isinstance(v,Path) else v for k,v in target.items()},"source":{k:str(v) if isinstance(v,Path) else v for k,v in source.items()},"repetition":repetition,"param_file":str(param_file),"log_dir":str(log_dir),"basis_dir":str(basis_dir),"ebf_dir":str(ebf_dir),"bound_tolerance":bound_tolerance,"compress_output":compress_output,"write_artifacts":write_artifacts,"run_index":run_index,"total_runs":total_runs,"experiment_index":experiment_index,"total_experiments":total_experiments,"total_repetitions":total_repetitions,"result_path":str(result_path)}
    with config_path.open("w",encoding="utf-8") as f: json.dump(config,f)
    command=["/usr/bin/time","-v","perf","stat","-e","cycles,instructions,task-clock,cpu-clock","--",sys.executable,str(Path(__file__).resolve()),"--worker-config",str(config_path)]
    print("Measuring complete trial with: "+" ".join(command)); sys.stdout.flush()
    completed=subprocess.run(command,stderr=sys.stdout)
    log_file=Path(log_dir)/f"{prefix}.{adapter.name}.log"
    row=blank_result(adapter,target,source,repetition,param_file,log_file)
    if result_path.is_file():
        try:
            with result_path.open("r",encoding="utf-8") as f: row=json.load(f)
        except Exception as exc: row["message"]=append_message(row["message"],f"Could not read worker result: {exc}")
    else:
        row["message"]=append_message(row["message"],"Measured worker produced no result file")
    if completed.returncode:
        row["solver_status"]="ERROR"
        row["message"]=append_message(row["message"],f"/usr/bin/time or perf worker exited with status {completed.returncode}")
    return row


def parse_arguments():
    p=argparse.ArgumentParser(description="Benchmark dual-simplex warm starts with Gurobi, COPT, HiGHS or Xpress")
    p.add_argument("solver",choices=["gurobi","copt","highs","xpress"]); p.add_argument("data_csv",help="CSV: name,lp_file,basis_file,basis_description"); p.add_argument("repetitions",type=int); p.add_argument("param_file"); p.add_argument("results_dir")
    p.add_argument("--bound-tolerance",type=float,default=1e-9,help="Tolerance for EBF bound_status classification")
    p.add_argument("--compress-output",action=argparse.BooleanOptionalAction,default=True,help="Compress generated BAS/EBF files with gzip (default: enabled).")
    p.add_argument("--write-artifacts",action=argparse.BooleanOptionalAction,default=False,help="Write post-solve basis and EBF artifacts (default: disabled).")
    group=p.add_mutually_exclusive_group(required=True); group.add_argument("--experiments-csv"); group.add_argument("--all-experiments",action="store_true")
    return p.parse_args()


def main():
    if len(sys.argv)==3 and sys.argv[1]=="--worker-config": return run_worker(sys.argv[2])
    args=parse_arguments(); print("\n"+"="*100+"\nDUAL-SIMPLEX WARM-START BATCH BENCHMARK\n"+"="*100+"\n")
    if args.repetitions<=0: print("ERROR: repetitions must be positive",file=sys.stderr); return 1
    if args.bound_tolerance<0: print("ERROR: --bound-tolerance must be nonnegative",file=sys.stderr); return 1
    data_csv=Path(args.data_csv).expanduser().resolve(); param_file=Path(args.param_file).expanduser().resolve(); results_dir=Path(args.results_dir).expanduser().resolve(); experiments_csv=Path(args.experiments_csv).expanduser().resolve() if args.experiments_csv else None
    try: adapter=get_solver_adapter(args.solver)
    except Exception as exc: print(f"ERROR loading solver adapter {args.solver!r}: {exc}",file=sys.stderr); return 1
    try:
        datasets=read_data_csv(data_csv); check_dataset_files(datasets); lookup={d["name"]:d for d in datasets}
        if len(datasets)<2: raise ValueError("At least two datasets are required")
        experiments=build_all_experiments(datasets) if args.all_experiments else read_experiments_csv(experiments_csv,lookup)
        if not experiments: raise ValueError("No experiments selected")
        if not param_file.is_file(): raise FileNotFoundError(f"Parameter/options file not found: {param_file}")
        print("Checking solver parameter/options file..."); sys.stdout.flush(); validated=adapter.validate_parameter_file(param_file,experiments[0][0]["lp_file"])
    except Exception as exc: print(f"\nPREFLIGHT CHECK FAILED:\n{exc}",file=sys.stderr); return 1
    total_runs=len(experiments)*args.repetitions
    try:
        sys.stdout.flush()
        experiment_dir=create_unique_experiment_dir(results_dir)
        print("\n"+"="*80+"\nEXPERIMENT PLAN\n"+"="*80); print(f"Solver                     : {adapter.name}\nOutput folder              : {experiment_dir}\nDatasets                   : {len(datasets)}\nSelection mode             : {'all ordered combinations' if args.all_experiments else 'explicit subset'}\nSelected experiments       : {len(experiments)}\nRepetitions per experiment : {args.repetitions}\nTotal optimization runs    : {total_runs}\nValidated solver settings  : {validated}\nWrite post-solve artifacts : {args.write_artifacts}\nEBF bound tolerance        : {args.bound_tolerance}\nCompress output            : {args.compress_output}")
        print("\nSelected experiments:")
        for i,(a,b) in enumerate(experiments,1): print(f"  [{i}] {a['name']} <- basis from {b['name']}")
        log_dir=experiment_dir/"logs"; basis_dir=experiment_dir/"optimal_bases"; ebf_dir=experiment_dir/"ebf_bases"; worker_dir=experiment_dir/"workers"
        for d in (log_dir,basis_dir,ebf_dir,worker_dir): d.mkdir()
        copied_param=experiment_dir/adapter.input_parameter_filename; shutil.copy2(param_file,copied_param)
        effective_param=experiment_dir/adapter.effective_parameter_filename; adapter.write_effective_parameters(copied_param,experiments[0][0]["lp_file"],effective_param)
        shutil.copy2(data_csv,experiment_dir/"input_data.csv")
        if experiments_csv: shutil.copy2(experiments_csv,experiment_dir/"input_experiments.csv")
        write_selected_experiments_csv(experiment_dir/"selected_experiments.csv",experiments)
        write_experiment_info(experiment_dir/"experiment_info.txt",adapter,args,data_csv,experiments_csv,copied_param,effective_param,datasets,experiments,validated)
        detailed=experiment_dir/"summary.csv"; short=experiment_dir/"summary_short.csv"; initialize_csv(detailed,DETAILED_SUMMARY_COLUMNS); initialize_csv(short,SHORT_SUMMARY_COLUMNS)
        run_index=0; succeeded_runs=0; failed_runs=0
        for exp_index,(target,source) in enumerate(experiments,1):
            for repetition in range(1,args.repetitions+1):
                run_index+=1
                row=run_measured_trial(adapter,target,source,repetition,copied_param,log_dir,basis_dir,ebf_dir,args.bound_tolerance,args.compress_output,args.write_artifacts,run_index,total_runs,exp_index,len(experiments),args.repetitions,worker_dir)
                append_csv_row(detailed,DETAILED_SUMMARY_COLUMNS,row); append_csv_row(short,SHORT_SUMMARY_COLUMNS,row)
                if row["is_optimal"]: succeeded_runs+=1
                else: failed_runs+=1
        print("\n"+"="*80+"\nEXPERIMENT SUMMARY\n"+"="*80)
        print(f"Total runs              : {total_runs}\nSolved to optimality    : {succeeded_runs}\nNot solved to optimality: {failed_runs}\nResults                 : {experiment_dir}")
        return 0
    except Exception as exc:
        print(f"\nFATAL ERROR:\n{exc}\n{traceback.format_exc()}",file=sys.stderr); return 1


if __name__=="__main__": raise SystemExit(main())
