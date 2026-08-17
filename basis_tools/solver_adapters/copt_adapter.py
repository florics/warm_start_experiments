from __future__ import annotations
from dataclasses import dataclass
import math
from pathlib import Path

from basis_tools.ebf import BasisStatus, ConstraintBasisEntry, VariableBasisEntry, classify_bound_status
from basis_tools.io_utils import materialize_input, materialize_output, logical_path


@dataclass
class CoptHandle:
    env: object
    model: object


class CoptAdapter:
    name = "copt"
    input_parameter_filename = "input_parameters.par"
    effective_parameter_filename = "effective_parameters.par"
    native_basis_extension = ".bas"
    _ATTRIBUTES_TO_PRINT = ["Status","LpStatus","HasSol","HasLpSol","HasBasis","ObjVal","ObjBound","LpObjval","SolvingTime","SimplexIter","BarrierIter","Cols","Rows","Elems"]
    _PARAMETERS_TO_PRINT = ["LpMethod","Threads","SimplexThreads","Presolve","FeasTol","DualTol","MatrixTol","Scaling","DualPrice","DualPerturb","TimeLimit"]

    def __init__(self):
        import coptpy as cp
        from coptpy import COPT
        self.cp, self.COPT = cp, COPT

    def version_info(self):
        parts = [str(getattr(self.COPT, a)) for a in ("VERSION_MAJOR","VERSION_MINOR","VERSION_TECHNICAL") if getattr(self.COPT,a,None) is not None]
        return {"solver":"COPT","solver_version":".".join(parts) if parts else "unknown","python_api":"coptpy","python_api_version":getattr(self.cp,"__version__","unknown")}

    def _new_handle(self, name):
        env = self.cp.Envr(); model = env.createModel(name); return CoptHandle(env, model)

    def validate_parameter_file(self, param_file: Path, reference_lp: Path):
        if param_file.suffix.lower() != ".par": raise ValueError(f"COPT parameter file must end in .par: {param_file}")
        h = self._new_handle("parameter_check")
        try:
            h.model.readParam(str(param_file)); method = h.model.getParam(self.COPT.Param.LpMethod)
            if method != 1: raise ValueError(f"COPT warm-start experiments require LpMethod=1; got {method}")
            return {"LpMethod": method}
        finally: self.dispose(h)

    def write_effective_parameters(self, param_file: Path, reference_lp: Path, output_path: Path):
        h = self._new_handle("effective_parameter_check")
        try:
            h.model.readParam(str(param_file))
            if h.model.getParam(self.COPT.Param.LpMethod) != 1: raise ValueError("LpMethod != 1")
            h.model.writeParam(str(output_path))
        finally: self.dispose(h)

    def load_model(self, lp_path: Path):
        h = self._new_handle(logical_path(lp_path).stem)
        try:
            with materialize_input(lp_path, expected_suffix=".lp") as local:
                h.model.read(str(local))
            return h
        except Exception:
            self.dispose(h); raise

    def read_parameters(self, h, param_file): h.model.readParam(str(param_file))
    def validate_loaded_parameters(self, h):
        method = h.model.getParam(self.COPT.Param.LpMethod)
        if method != 1: raise ValueError(f"Effective COPT LpMethod={method}; required 1")
    def set_log_file(self, h, log_file): h.model.setLogFile(str(log_file))
    def read_basis(self, h, basis_file):
        with materialize_input(basis_file, expected_suffix=".bas") as local:
            h.model.readBasis(str(local))
    read_native_basis = read_basis
    def optimize(self, h): h.model.solveLP()
    def solve(self, h, parameter_file=None, log_file=None):
        if parameter_file: self.read_parameters(h, parameter_file)
        if log_file: self.set_log_file(h, log_file)
        self.optimize(h)

    @staticmethod
    def _safe_attr(model, name):
        try: return model.getAttr(name)
        except Exception:
            try: return getattr(model, name)
            except Exception: return None

    def collect_result(self, h, external_wallclock=None):
        m=h.model; status_code=int(m.status); has_sol=self._safe_attr(m,"HasSol")
        return {"status":self._status_name(status_code),"status_code":status_code,"is_optimal":status_code==self.COPT.OPTIMAL,"objective_value":self._safe_attr(m,"ObjVal") if has_sol else None,"solve_time_s":self._safe_attr(m,"SolvingTime"),"external_wallclock_s":external_wallclock,"simplex_iterations":self._safe_attr(m,"SimplexIter"),"barrier_iterations":self._safe_attr(m,"BarrierIter"),"work_units":None}

    def _status_name(self, code):
        for name in ("UNSTARTED","OPTIMAL","INFEASIBLE","UNBOUNDED","INF_OR_UNB","NUMERICAL","NODELIMIT","IMPRECISE","TIMEOUT","UNFINISHED","INTERRUPTED","ITERLIMIT"):
            value=getattr(self.COPT,name,None)
            if value is not None and code==value: return name
        return f"OTHER({code})"

    def print_model_information(self,h):
        print("\n--- COPT model statistics ---\n")
        for name in ("Cols","Rows","Elems"): print(f"{name}: {self._safe_attr(h.model,name)}")
        print("\n--- Important effective COPT parameters ---\n")
        for name in self._PARAMETERS_TO_PRINT:
            try: print(f"{name}: {h.model.getParam(getattr(self.COPT.Param,name))}")
            except Exception: print(f"{name}: not available")
        print()

    def print_postsolve_information(self,h,external_wallclock=0.0):
        print("\n"+"="*80); print("COPT POST-SOLVE INFORMATION"); print("="*80)
        if external_wallclock is not None: print(f"External wallclock time: {external_wallclock:.6f} sec")
        for name in self._ATTRIBUTES_TO_PRINT: print(f"{name}: {self._safe_attr(h.model,name)}")
        print("="*80+"\n")
    def print_diagnostics(self,h): self.print_postsolve_information(h,None)

    def has_basis(self,h): return bool(self._safe_attr(h.model,"HasBasis"))
    def write_basis(self,h,output_path):
        with materialize_output(output_path, expected_suffix=".bas") as local:
            h.model.writeBasis(str(local))
    write_native_basis = write_basis
    def write_exchange_bas(self, h, native_basis, exchange_bas): self.write_basis(h, exchange_bas)
    def get_num_rows(self,h): return int(self._safe_attr(h.model,"Rows"))
    def get_simplex_iterations(self,h): return self._safe_attr(h.model,"SimplexIter")

    def get_basic_membership(self,h):
        m=h.model; vars_=list(m.getVars()); cons=list(m.getConstrs())
        vb=list(m.getVarBasis()); cb=list(m.getConstrBasis())
        def vname(v):
            try: return v.getName()
            except Exception: return v.name
        def cname(c):
            try: return c.getName()
            except Exception: return c.name
        return ({vname(v): s == self.COPT.BASIS_BASIC for v,s in zip(vars_,vb)}, {cname(c): s == self.COPT.BASIS_BASIC for c,s in zip(cons,cb)})

    def _canonical_bound(self,value):
        x=float(value); inf=float(self.COPT.INFINITY)
        if x<=-inf: return -math.inf
        if x>=inf: return math.inf
        return x

    def extract_ebf_entries(self,h,*,tolerance=1e-9):
        m=h.model; vars_=list(m.getVars()); cons=list(m.getConstrs()); values=list(m.getValues()); vb=list(m.getVarBasis()); cb=list(m.getConstrBasis())
        activities=[float(m.getRow(c).getValue()) for c in cons]
        def bs(native):
            if native==self.COPT.BASIS_BASIC: return BasisStatus.BASIC
            if native==self.COPT.BASIS_SUPERBASIC: return BasisStatus.SUPERBASIC
            if native in {self.COPT.BASIS_LOWER,self.COPT.BASIS_UPPER,self.COPT.BASIS_FIXED}: return BasisStatus.NONBASIC
            raise ValueError(f"Unknown COPT basis status {native}")
        variables=[]
        for v,value,native in zip(vars_,values,vb):
            value=float(value); bound=classify_bound_status(self._canonical_bound(v.LB),self._canonical_bound(v.UB),value,tolerance=tolerance)
            variables.append(VariableBasisEntry(v.name,bs(native),bound,value))
        constraints=[]
        for c,activity,native in zip(cons,activities,cb):
            bound=classify_bound_status(self._canonical_bound(c.LB),self._canonical_bound(c.UB),activity,tolerance=tolerance)
            constraints.append(ConstraintBasisEntry(c.name,bs(native),bound,activity))
        return variables,constraints

    def dispose(self,h):
        if h is None: return
        try: h.model.close()
        except Exception:
            try: h.model.clear()
            except Exception: pass
        try: h.env.close()
        except Exception: pass
