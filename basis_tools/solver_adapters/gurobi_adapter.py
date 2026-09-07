from __future__ import annotations
import math
from pathlib import Path

from basis_tools.ebf import BasisStatus, BoundStatus, ConstraintBasisEntry, VariableBasisEntry, classify_bound_status
from basis_tools.io_utils import materialize_input, materialize_output


class GurobiAdapter:
    name = "gurobi"
    input_parameter_filename = "input_parameters.prm"
    effective_parameter_filename = "effective_parameters.prm"
    native_basis_extension = ".bas"

    _ATTRIBUTES_TO_PRINT = [
        "Status", "SolCount", "ObjVal", "ObjBound", "Runtime", "IterCount",
        "BarIterCount", "Work", "MaxMemUsed", "MaxVio", "BoundVio",
        "ConstrVio", "ConstrResidual", "DualVio", "DualResidual", "ComplVio",
    ]
    _PARAMETERS_TO_PRINT = [
        "Method", "Threads", "Presolve", "LPWarmStart", "FeasibilityTol",
        "OptimalityTol", "MarkowitzTol", "ScaleFlag", "NumericFocus",
        "IterationLimit", "TimeLimit", "WorkLimit",
    ]

    def __init__(self):
        import gurobipy as gp
        self.gp = gp
        self.GRB = gp.GRB

    def version_info(self):
        try:
            solver_version = ".".join(str(x) for x in self.gp.gurobi.version())
        except Exception:
            solver_version = "unknown"
        return {"solver": "Gurobi", "solver_version": solver_version, "python_api": "gurobipy", "python_api_version": getattr(self.gp, "__version__", "unknown")}

    def validate_parameter_file(self, param_file: Path, reference_lp: Path):
        if param_file.suffix.lower() != ".prm":
            raise ValueError(f"Gurobi parameter file must end in .prm: {param_file}")
        with self.gp.Model("parameter_check") as model:
            model.read(str(param_file))
            method = model.Params.Method
            if method != 1:
                raise ValueError(f"Gurobi warm-start experiments require dual simplex: Method={method}, required 1")
            return {"Method": method}

    def write_effective_parameters(self, param_file: Path, reference_lp: Path, output_path: Path):
        with self.gp.Model("effective_parameter_check") as model:
            model.read(str(param_file))
            if model.Params.Method != 1:
                raise ValueError("Refusing to write effective parameters because Method != 1")
            model.write(str(output_path))

    def load_model(self, lp_path: Path):
        with materialize_input(lp_path, expected_suffix=".lp") as local:
            return self.gp.read(str(local))

    def read_parameters(self, model, param_file: Path):
        model.read(str(param_file))

    def validate_loaded_parameters(self, model):
        if model.Params.Method != 1:
            raise ValueError(f"Effective Gurobi Method={model.Params.Method}; required Method=1")

    def set_log_file(self, model, log_file: Path):
        model.Params.LogFile = str(log_file)

    def read_basis(self, model, basis_file: Path):
        with materialize_input(basis_file, expected_suffix=".bas") as local:
            model.read(str(local))

    read_native_basis = read_basis

    def optimize(self, model):
        model.optimize()

    def solve(self, model, parameter_file=None, log_file=None):
        if parameter_file:
            self.read_parameters(model, parameter_file)
        if log_file:
            self.set_log_file(model, log_file)
        self.optimize(model)

    @staticmethod
    def _safe_attr(model, name):
        try:
            return model.getAttr(name)
        except Exception:
            return None

    def collect_result(self, model, external_wallclock=None):
        status_code = int(model.Status)
        sol_count = self._safe_attr(model, "SolCount")
        return {
            "status": self._status_name(status_code), "status_code": status_code,
            "is_optimal": status_code == self.GRB.OPTIMAL,
            "objective_value": self._safe_attr(model, "ObjVal") if sol_count and sol_count > 0 else None,
            "solve_time_s": self._safe_attr(model, "Runtime"),
            "external_wallclock_s": external_wallclock,
            "simplex_iterations": self._safe_attr(model, "IterCount"),
            "barrier_iterations": self._safe_attr(model, "BarIterCount"),
            "work_units": self._safe_attr(model, "Work"),
        }

    def _status_name(self, status_code):
        for name in ("LOADED","OPTIMAL","INFEASIBLE","INF_OR_UNBD","UNBOUNDED","CUTOFF","ITERATION_LIMIT","TIME_LIMIT","INTERRUPTED","NUMERIC","SUBOPTIMAL","USER_OBJ_LIMIT","WORK_LIMIT","MEM_LIMIT"):
            code = getattr(self.GRB, name, None)
            if code is not None and status_code == code:
                return name
        return f"OTHER({status_code})"

    def print_model_information(self, model):
        print("\n--- Gurobi model statistics ---\n")
        try: model.printStats()
        except Exception as exc: print(f"model.printStats() failed: {exc}")
        print("\n--- Important effective Gurobi parameters ---\n")
        for parameter in self._PARAMETERS_TO_PRINT:
            try: print(f"{parameter}: {model.getParamInfo(parameter)[2]}")
            except Exception: print(f"{parameter}: not available")
        print()

    def print_postsolve_information(self, model, external_wallclock=0.0):
        print("\n" + "="*80); print("GUROBI POST-SOLVE INFORMATION"); print("="*80)
        if external_wallclock is not None:
            print(f"External wallclock time: {external_wallclock:.6f} sec")
        for name in self._ATTRIBUTES_TO_PRINT:
            value = self._safe_attr(model, name)
            print(f"{name}: {'not available' if value is None else value}")
        try: model.printQuality()
        except Exception as exc: print(f"model.printQuality() not available: {exc}")
        print("="*80 + "\n")

    def print_diagnostics(self, model):
        self.print_postsolve_information(model, None)

    def has_basis(self, model):
        try:
            vars_ = model.getVars(); cons = model.getConstrs()
            if vars_: _ = vars_[0].VBasis
            elif cons: _ = cons[0].CBasis
            return True
        except Exception:
            return False

    def write_basis(self, model, output_path: Path):
        with materialize_output(output_path, expected_suffix=".bas") as local:
            model.write(str(local))

    write_native_basis = write_basis

    def write_solution(self, model, output_path: Path):
        with materialize_output(output_path, expected_suffix=".sol") as local:
            model.write(str(local))

    def write_exchange_bas(self, model, native_basis, exchange_bas):
        self.write_basis(model, exchange_bas)

    def get_simplex_iterations(self, model):
        value = self._safe_attr(model, "IterCount")
        return None if value is None else float(value)

    def get_basic_membership(self, model):
        return (
            {v.VarName: int(v.VBasis) == 0 for v in model.getVars()},
            {c.ConstrName: int(c.CBasis) == 0 for c in model.getConstrs()},
        )

    def get_model_names(self, model):
        return [v.VarName for v in model.getVars()], [c.ConstrName for c in model.getConstrs()]

    def _canonical_bound(self, value):
        x = float(value); inf = float(self.GRB.INFINITY)
        if x <= -inf: return -math.inf
        if x >= inf: return math.inf
        return x

    def extract_ebf_entries(self, model, *, tolerance=1e-9):
        variables = []
        for v in model.getVars():
            native = int(v.VBasis); value = float(v.X)
            basis_status = {0: BasisStatus.BASIC, -1: BasisStatus.NONBASIC, -2: BasisStatus.NONBASIC, -3: BasisStatus.SUPERBASIC}.get(native)
            if basis_status is None:
                raise ValueError(f"Unknown Gurobi VBasis status {native} for {v.VarName}")
            lower, upper = self._canonical_bound(v.LB), self._canonical_bound(v.UB)
            bound_status = classify_bound_status(lower, upper, value, tolerance=tolerance)
            fixed = math.isfinite(lower) and math.isfinite(upper) and abs(upper-lower) <= tolerance
            if native == -1: bound_status = BoundStatus.FIXED if fixed else BoundStatus.LOWER
            elif native == -2: bound_status = BoundStatus.FIXED if fixed else BoundStatus.UPPER
            variables.append(VariableBasisEntry(v.VarName, basis_status, bound_status, value, lower, upper))
        constraints = []
        for c in model.getConstrs():
            native = int(c.CBasis)
            if native == 0: basis_status = BasisStatus.BASIC
            elif native == -1: basis_status = BasisStatus.NONBASIC
            else: raise ValueError(f"Unknown Gurobi CBasis status {native} for {c.ConstrName}")
            activity = float(model.getRow(c).getValue())
            if c.Sense == "<": lower, upper = -math.inf, float(c.RHS)
            elif c.Sense == ">": lower, upper = float(c.RHS), math.inf
            elif c.Sense == "=": lower = upper = float(c.RHS)
            else: raise ValueError(f"Unknown Gurobi sense {c.Sense!r} for {c.ConstrName}")
            bound_status = classify_bound_status(lower, upper, activity, tolerance=tolerance)
            constraints.append(ConstraintBasisEntry(c.ConstrName, basis_status, bound_status, activity, lower, upper))
        return variables, constraints

    def get_num_rows(self, model):
        return int(model.NumConstrs)

    def dispose(self, model):
        try: model.dispose()
        except Exception: pass
