from __future__ import annotations
from dataclasses import dataclass
import math
from pathlib import Path
import tempfile

from basis_tools.ebf import BasisStatus, BoundStatus, ConstraintBasisEntry, VariableBasisEntry, classify_bound_status
from basis_tools.io_utils import materialize_input, materialize_output
from basis_tools.mps_bas import BASIC, LOWER, NONBASIC, UPPER, ZERO, first_nonempty_line, parse_mps_bas, convert_highs_basis_file_to_mps_bas


@dataclass
class HighsHandle:
    highs: object
    solver_runtime_delta: float | None = None
    run_status: object | None = None


class HighsAdapter:
    name = "highs"
    input_parameter_filename = "input_parameters.options"
    effective_parameter_filename = "effective_parameters.options"
    native_basis_extension = ".highs.bas"
    _OPTIONS_TO_PRINT = ["solver","simplex_strategy","threads","parallel","presolve","primal_feasibility_tolerance","dual_feasibility_tolerance","simplex_dual_edge_weight_strategy","simplex_iteration_limit","time_limit"]
    _INFO_TO_PRINT = ["valid","objective_function_value","simplex_iteration_count","ipm_iteration_count","crossover_iteration_count","primal_solution_status","dual_solution_status","basis_validity","num_primal_infeasibilities","max_primal_infeasibility","num_dual_infeasibilities","max_dual_infeasibility","max_primal_residual_error","max_dual_residual_error","max_complementarity_violation","primal_dual_objective_error"]

    def __init__(self):
        import highspy
        self.highspy = highspy

    def version_info(self):
        version=getattr(self.highspy,"__version__",None)
        if version is None:
            try: version=self.highspy.Highs().version()
            except Exception: version="unknown"
        return {"solver":"HiGHS","solver_version":str(version),"python_api":"highspy","python_api_version":str(getattr(self.highspy,"__version__","unknown"))}

    def _require_ok(self,status,action):
        if status != self.highspy.HighsStatus.kOk:
            raise RuntimeError(f"HiGHS {action} failed with status {status}")

    def _get_option(self,highs,name):
        result=highs.getOptionValue(name)
        if not isinstance(result,(tuple,list)) or len(result)<2:
            raise RuntimeError(f"Unexpected getOptionValue({name!r}) result: {result!r}")
        self._require_ok(result[0],f"getOptionValue({name})"); return result[1]

    def _validate_dual_simplex_options(self,highs):
        solver=str(self._get_option(highs,"solver")).lower(); strategy=int(self._get_option(highs,"simplex_strategy"))
        if solver != "simplex": raise ValueError(f"HiGHS requires solver='simplex'; got {solver!r}")
        if strategy not in (1,2,3): raise ValueError(f"HiGHS requires dual simplex strategy 1, 2 or 3; got {strategy}")
        return {"solver":solver,"simplex_strategy":strategy}

    def validate_parameter_file(self,param_file:Path,reference_lp:Path):
        h=self.highspy.Highs(); self._require_ok(h.readOptions(str(param_file)),f"readOptions({param_file})"); return self._validate_dual_simplex_options(h)

    def write_effective_parameters(self,param_file:Path,reference_lp:Path,output_path:Path):
        h=self.highspy.Highs(); self._require_ok(h.readOptions(str(param_file)),f"readOptions({param_file})"); self._validate_dual_simplex_options(h)
        self._require_ok(h.writeOptions(str(output_path)),f"writeOptions({output_path})")

    def load_model(self,lp_path:Path):
        h=self.highspy.Highs()
        with materialize_input(lp_path, expected_suffix=".lp") as local:
            self._require_ok(h.readModel(str(local)),f"readModel({lp_path})")
        return HighsHandle(h)

    def read_parameters(self,handle,param_file): self._require_ok(handle.highs.readOptions(str(param_file)),f"readOptions({param_file})")
    def validate_loaded_parameters(self,handle): self._validate_dual_simplex_options(handle.highs)
    def set_log_file(self,handle,log_file): self._require_ok(handle.highs.setOptionValue("log_file",str(log_file)),"setOptionValue(log_file)")

    def _model_names(self,highs):
        lp=highs.getLp()
        col_names=list(lp.col_names_) if len(lp.col_names_)==lp.num_col_ else [f"col_{i}" for i in range(lp.num_col_)]
        row_names=list(lp.row_names_) if len(lp.row_names_)==lp.num_row_ else [f"row_{i}" for i in range(lp.num_row_)]
        return col_names,row_names

    def read_basis(self,handle,basis_file:Path):
        h=handle.highs; header=first_nonempty_line(basis_file)
        if header.startswith("HiGHS_basis_file"):
            with materialize_input(basis_file, expected_suffix=".bas") as local:
                self._require_ok(h.readBasis(str(local)),f"readBasis({basis_file})")
        elif header.startswith("NAME"):
            col_names,row_names=self._model_names(h)
            parsed=parse_mps_bas(basis_file,col_names,row_names)
            H=self.highspy.HighsBasisStatus
            to_native={LOWER:H.kLower,BASIC:H.kBasic,UPPER:H.kUpper}
            basis=self.highspy.HighsBasis(); basis.col_status=[to_native[s] for s in parsed.col_status]; basis.row_status=[to_native[s] for s in parsed.row_status]
            self._require_ok(h.setBasis(basis),f"setBasis(parsed MPS BAS {basis_file})")
        else:
            raise ValueError(f"Unsupported HiGHS basis input {basis_file}: expected first line 'HiGHS_basis_file...' or 'NAME ...'")
        loaded=h.getBasis()
        if not bool(getattr(loaded,"valid",False)):
            raise RuntimeError(f"Basis {basis_file} was accepted but HiGHS reports it as invalid")

    read_native_basis = read_basis

    def optimize(self,handle):
        before=float(handle.highs.getRunTime()); status=handle.highs.run(); after=float(handle.highs.getRunTime())
        handle.solver_runtime_delta=max(0.0,after-before); handle.run_status=status
        if status == self.highspy.HighsStatus.kError: raise RuntimeError("HiGHS run() returned kError")

    def solve(self, handle, parameter_file=None, log_file=None):
        if parameter_file: self.read_parameters(handle, parameter_file)
        if log_file: self.set_log_file(handle, log_file)
        self.optimize(handle)

    def collect_result(self,handle,external_wallclock=None):
        h=handle.highs; info=h.getInfo(); model_status=h.getModelStatus(); status_name=h.modelStatusToString(model_status)
        try: status_code=int(model_status.value)
        except Exception:
            try: status_code=int(model_status)
            except Exception: status_code=str(model_status)
        objective=getattr(info,"objective_function_value",None) if bool(getattr(info,"valid",False)) else None
        return {"status":status_name,"status_code":status_code,"is_optimal":model_status==self.highspy.HighsModelStatus.kOptimal,"objective_value":objective,"solve_time_s":handle.solver_runtime_delta,"external_wallclock_s":external_wallclock,"simplex_iterations":getattr(info,"simplex_iteration_count",None),"barrier_iterations":getattr(info,"ipm_iteration_count",None),"work_units":None}

    def print_model_information(self,handle):
        h=handle.highs; lp=h.getLp(); print("\n--- HiGHS model statistics ---\n"); print(f"Columns: {lp.num_col_}\nRows: {lp.num_row_}\nNonzeros: {h.getNumNz()}")
        print("\n--- Important effective HiGHS options ---\n")
        for name in self._OPTIONS_TO_PRINT:
            try: print(f"{name}: {self._get_option(h,name)}")
            except Exception: print(f"{name}: not available")
        print()

    def print_postsolve_information(self,handle,external_wallclock=0.0):
        h=handle.highs; print("\n"+"="*80); print("HIGHS POST-SOLVE INFORMATION"); print("="*80)
        if external_wallclock is not None: print(f"External wallclock time: {external_wallclock:.6f} sec")
        print(f"HiGHS run-time delta: {handle.solver_runtime_delta}")
        try: print(f"Model status: {h.modelStatusToString(h.getModelStatus())}")
        except Exception: pass
        try:
            info=h.getInfo()
            for name in self._INFO_TO_PRINT:
                value=getattr(info,name,None); print(f"{name}: {'not available' if value is None else value}")
        except Exception as exc: print(f"getInfo() failed: {exc}")
        print("="*80+"\n")
    def print_diagnostics(self,handle): self.print_postsolve_information(handle,None)

    def has_basis(self,handle):
        try: return bool(handle.highs.getBasis().valid)
        except Exception: return False

    def _symbolic_status(self,native):
        H=self.highspy.HighsBasisStatus
        if native==H.kLower: return LOWER
        if native==H.kBasic: return BASIC
        if native==H.kUpper: return UPPER
        if native==H.kZero: return ZERO
        if native==H.kNonbasic: return NONBASIC
        raise ValueError(f"Unknown HiGHS basis status {native!r}")

    def write_native_basis(self,handle,output_path:Path):
        if not self.has_basis(handle): raise RuntimeError("HiGHS has no valid basis to write")
        with materialize_output(output_path, expected_suffix=".bas") as local:
            self._require_ok(handle.highs.writeBasis(str(local)),f"writeBasis({output_path})")

    def convert_native_highs_basis_to_bas(self,handle,input_path:Path,output_path:Path):
        col_names,row_names=self._model_names(handle.highs)
        convert_highs_basis_file_to_mps_bas(input_path,output_path,expected_col_names=col_names,expected_row_names=row_names)

    def write_exchange_bas(self, handle, native_basis, exchange_bas):
        self.convert_native_highs_basis_to_bas(handle, native_basis, exchange_bas)

    def write_basis(self, handle, output_path: Path):
        """Write standard classical BAS via the existing HiGHS native converter."""
        with tempfile.TemporaryDirectory(prefix="highs_basis_convert_") as td:
            native = Path(td) / "basis.highs.bas"
            self.write_native_basis(handle, native)
            self.convert_native_highs_basis_to_bas(handle, native, output_path)

    def get_num_rows(self,handle): return int(handle.highs.getNumRow())
    def get_simplex_iterations(self,handle):
        try: return getattr(handle.highs.getInfo(),"simplex_iteration_count",None)
        except Exception: return None

    def get_basic_membership(self,handle):
        h=handle.highs; basis=h.getBasis(); col_names,row_names=self._model_names(h); H=self.highspy.HighsBasisStatus
        return ({n:s==H.kBasic for n,s in zip(col_names,basis.col_status)}, {n:s==H.kBasic for n,s in zip(row_names,basis.row_status)})

    def _canonical_bound(self,value):
        x=float(value); inf=float(getattr(self.highspy,"kHighsInf",math.inf))
        if math.isfinite(inf):
            if x<=-inf: return -math.inf
            if x>=inf: return math.inf
        return x

    def extract_ebf_entries(self,handle,*,tolerance=1e-9):
        h=handle.highs
        lp=h.getLp()
        solution=h.getSolution()
        basis=h.getBasis()
        if not bool(getattr(basis,"valid",False)): raise RuntimeError("HiGHS has no valid basis")
        col_values=list(solution.col_value); row_values=list(solution.row_value); col_status=list(basis.col_status); row_status=list(basis.row_status)
        col_lower=list(lp.col_lower_); col_upper=list(lp.col_upper_); row_lower=list(lp.row_lower_); row_upper=list(lp.row_upper_)
        col_names,row_names=self._model_names(h); H=self.highspy.HighsBasisStatus
        def canonical(native,bound):
            if native==H.kBasic: return BasisStatus.BASIC
            if native==H.kZero: return BasisStatus.SUPERBASIC
            if native==H.kNonbasic:
                return BasisStatus.NONBASIC if bound in {BoundStatus.LOWER,BoundStatus.UPPER,BoundStatus.FIXED} else BasisStatus.SUPERBASIC
            if native in {H.kLower,H.kUpper}: return BasisStatus.NONBASIC
            raise ValueError(f"Unknown HiGHS basis status {native}")
        variables=[]
        for i in range(lp.num_col_):
            value=float(col_values[i])
            lower=self._canonical_bound(col_lower[i])
            upper=self._canonical_bound(col_upper[i])
            bound=classify_bound_status(lower,upper,value,tolerance=tolerance)
            entry=VariableBasisEntry(col_names[i],canonical(col_status[i],bound),bound,value,lower,upper)
            variables.append(entry)
        constraints=[]
        for i in range(lp.num_row_):
            activity=float(row_values[i])
            lower=self._canonical_bound(row_lower[i])
            upper=self._canonical_bound(row_upper[i])
            bound=classify_bound_status(lower,upper,activity,tolerance=tolerance)
            entry=ConstraintBasisEntry(row_names[i],canonical(row_status[i],bound),bound,activity,lower,upper)
            constraints.append(entry)
        return variables,constraints

    def dispose(self,handle):
        if handle is None: return
        try: handle.highs.clear()
        except Exception: pass
