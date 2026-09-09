from __future__ import annotations
import math
from pathlib import Path
import tempfile
import zipfile

from basis_tools.ebf import BasisStatus, BoundStatus, ConstraintBasisEntry, VariableBasisEntry, classify_bound_status
from basis_tools.io_utils import materialize_input, materialize_output


class XpressAdapter:
    name="xpress"
    input_parameter_filename="input_parameters.prs"
    effective_parameter_filename="effective_parameters.prs"
    native_basis_extension=".bas"

    def __init__(self):
        import xpress as xp
        self.xp=xp

    def version_info(self):
        version=getattr(self.xp,"__version__",None)
        if version is None:
            for candidate in ("getversion","getVersion"):
                fn=getattr(self.xp,candidate,None)
                if callable(fn):
                    try: version=fn(); break
                    except Exception: pass
        return {"solver":"FICO Xpress","solver_version":str(version or "unknown"),"python_api":"xpress","python_api_version":str(getattr(self.xp,"__version__","unknown"))}

    @staticmethod
    def _parse_value(text):
        s=text.strip(); lower=s.lower()
        if lower=="true": return True
        if lower=="false": return False
        try: return int(s,0)
        except ValueError: pass
        try: return float(s)
        except ValueError: return s.strip("'\"")

    @classmethod
    def _iter_controls(cls,parameter_file):
        for lineno,raw in enumerate(Path(parameter_file).read_text(encoding="utf-8").splitlines(),start=1):
            line=raw.strip()
            if not line or line.startswith(("#","!","//")): continue
            line=line.split("#",1)[0].strip()
            if not line: continue
            if "=" in line: name,value=line.split("=",1)
            else:
                parts=line.split(None,1)
                if len(parts)!=2: raise ValueError(f"{parameter_file}:{lineno}: expected CONTROL=VALUE or CONTROL VALUE")
                name,value=parts
            name=name.strip()
            if name.upper().startswith("XPRS_"): name=name[5:]
            yield lineno,name.lower(),cls._parse_value(value)

    def _apply_parameters(self,p,parameter_file):
        applied=[]
        for lineno,name,value in self._iter_controls(parameter_file):
            try: setattr(p.controls,name,value)
            except Exception as exc: raise ValueError(f"{parameter_file}:{lineno}: could not set Xpress control {name!r}={value!r}: {exc}") from exc
            applied.append(name)
        return applied

    def _validate_dual(self,p):
        lpflags=int(p.controls.lpflags); dual=int(self.xp.LPFlags.DUAL)
        if lpflags != dual: raise ValueError(f"Xpress warm-start experiments require LPFLAGS=DUAL ({dual}); got {lpflags}")
        return {"LPFLAGS":lpflags,"algorithm":"dual simplex"}

    def validate_parameter_file(self,param_file:Path,reference_lp:Path):
        p=self.xp.problem(); self._apply_parameters(p,param_file); return self._validate_dual(p)

    def write_effective_parameters(self,param_file:Path,reference_lp:Path,output_path:Path):
        p=self.xp.problem(); names=self._apply_parameters(p,param_file); self._validate_dual(p)
        with Path(output_path).open("w",encoding="utf-8") as f:
            for name in names: f.write(f"{name.upper()}={getattr(p.controls,name)}\n")

    def load_model(self,lp_path:Path):
        p=self.xp.problem()
        with materialize_input(lp_path, expected_suffix=".lp") as local:
            if hasattr(p, "readProb"): p.readProb(str(local))
            else: p.read(str(local))
        return p
    def read_parameters(self,p,param_file): self._apply_parameters(p,param_file)
    def validate_loaded_parameters(self,p): self._validate_dual(p)
    def set_log_file(self,p,log_file):
        method=getattr(p,"setLogFile",None)
        if callable(method): method(str(log_file))
    def read_basis(self,p,basis_file):
        with materialize_input(basis_file, expected_suffix=".bas") as local:
            if hasattr(p,"readBasis"): p.readBasis(str(local),"v")
            elif hasattr(p,"readbasis"): p.readbasis(str(local),"v")
            else: raise AttributeError("Xpress problem exposes neither readBasis nor readbasis")
    read_native_basis = read_basis
    def optimize(self,p): p.optimize()
    def solve(self,p,parameter_file=None,log_file=None):
        if parameter_file: self.read_parameters(p,parameter_file)
        if log_file: self.set_log_file(p,log_file)
        self.optimize(p)

    @staticmethod
    def _safe_attr(p,name):
        try: return getattr(p.attributes,name)
        except Exception: return None

    def collect_result(self,p,external_wallclock=None):
        # Preserve the later Xpress fix: SOLSTATUS=1 means optimal, and integer
        # status objects must not be classified by their string representation.
        solstatus=self._safe_attr(p,"solstatus"); lpstatus=self._safe_attr(p,"lpstatus"); solvestatus=self._safe_attr(p,"solvestatus")
        status_obj=solstatus if solstatus is not None else lpstatus
        is_optimal=False; status_name="UNKNOWN"
        if solstatus is not None:
            optimal_enum=getattr(getattr(self.xp,"SolStatus",None),"OPTIMAL",None)
            if optimal_enum is not None:
                try: is_optimal=(solstatus==optimal_enum) or (int(solstatus)==int(optimal_enum))
                except Exception: is_optimal=(solstatus==optimal_enum)
            if not is_optimal:
                try: is_optimal=int(solstatus)==1
                except Exception: pass
            try: status_name=solstatus.name
            except Exception: status_name="OPTIMAL" if is_optimal else f"SOLSTATUS({solstatus})"
        elif lpstatus is not None:
            try: is_optimal=int(lpstatus)==1
            except Exception: pass
            try: status_name=lpstatus.name
            except Exception: status_name="OPTIMAL" if is_optimal else f"LPSTATUS({lpstatus})"
        obj=self._safe_attr(p,"objval")
        if obj is None: obj=self._safe_attr(p,"lpobjval")
        return {"status":status_name,"status_code":status_obj,"is_optimal":is_optimal,"objective_value":obj,"solve_time_s":self._safe_attr(p,"time"),"external_wallclock_s":external_wallclock,"simplex_iterations":self._safe_attr(p,"simplexiter"),"barrier_iterations":self._safe_attr(p,"bariter"),"work_units":None,"solve_status":str(solvestatus)}

    def print_model_information(self,p):
        print("\n--- Xpress model statistics ---\n")
        for name in ("rows","cols","elems"): print(f"{name}: {self._safe_attr(p,name)}")
        print("\n--- Important effective Xpress controls ---\n")
        for name in ("lpflags","threads","presolve","feastol","optimalitytol","maxtime"):
            try: print(f"{name}: {getattr(p.controls,name)}")
            except Exception: print(f"{name}: not available")
        print()

    def print_postsolve_information(self,p,external_wallclock=0.0):
        print("\n"+"="*80); print("XPRESS POST-SOLVE INFORMATION"); print("="*80)
        if external_wallclock is not None: print(f"External wallclock time: {external_wallclock:.6f} sec")
        for name in ("solvestatus","solstatus","lpstatus","objval","lpobjval","rows","cols","elems","simplexiter","bariter","time"):
            print(f"{name}: {self._safe_attr(p,name)}")
        print("="*80+"\n")
    def print_diagnostics(self,p): self.print_postsolve_information(p,None)

    def _get_basis(self,p):
        if hasattr(p,"getBasis"):
            try:
                result=p.getBasis()
                if result is not None: return result
            except TypeError:
                r,c=[],[]; p.getBasis(r,c); return r,c
        if hasattr(p,"getbasis"):
            r,c=[],[]; p.getbasis(r,c); return r,c
        raise AttributeError("Xpress problem exposes neither getBasis nor getbasis")

    def has_basis(self,p):
        try:
            row,col=self._get_basis(p); return len(row)==int(p.attributes.rows) and len(col)==int(p.attributes.cols)
        except Exception: return False

    def write_basis(self,p,output_path):
        with materialize_output(output_path, expected_suffix=".bas") as local:
            if hasattr(p,"writeBasis"): p.writeBasis(str(local),"v")
            elif hasattr(p,"writebasis"): p.writebasis(str(local),"v")
            else: raise AttributeError("Xpress problem exposes neither writeBasis nor writebasis")
    write_native_basis = write_basis
    def write_solution(self,p,output_path):
        output_path=Path(output_path)
        if not str(output_path).endswith(".sol.zip"):
            raise ValueError(f"Xpress solution output must end in .sol.zip: {output_path}")
        output_path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xpress_solution_") as td:
            base=Path(td)/output_path.with_suffix("").name
            p.writeSol(str(base))
            asc=Path(f"{base}.asc"); hdr=Path(f"{base}.hdr")
            missing=[path for path in (asc,hdr) if not path.is_file()]
            if missing: raise RuntimeError(f"Xpress did not create expected solution files: {missing}")
            with zipfile.ZipFile(output_path,"w",compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(asc,arcname=asc.name); archive.write(hdr,arcname=hdr.name)
    def write_exchange_bas(self,p,native_basis,exchange_bas): self.write_basis(p,exchange_bas)
    def get_num_rows(self,p): return int(p.attributes.rows)
    def get_simplex_iterations(self,p):
        value=self._safe_attr(p,"simplexiter")
        try: return int(value) if value is not None else None
        except Exception: return value

    def get_basic_membership(self,p):
        vars_=list(p.getVariable()); cons=list(p.getConstraint()); row_status,col_status=self._get_basis(p)
        return ({v.name:int(s)==1 for v,s in zip(vars_,col_status)}, {c.name:int(s)==1 for c,s in zip(cons,row_status)})

    def get_model_names(self,p):
        return [v.name for v in p.getVariable()], [c.name for c in p.getConstraint()]

    def remove_rows(self,p,row_names):
        rows={c.name:c for c in p.getConstraint()}; missing=[name for name in row_names if name not in rows]
        if missing: raise ValueError(f"Xpress rows not found: {missing[:3]}")
        p.delConstraint([rows[name] for name in row_names])

    def add_equality_row(self,p,first_index,second_index,name):
        variables=p.getVariable(); p.addConstraint(self.xp.constraint(variables[first_index]-variables[second_index] == 0.0, name=name))

    def get_column_values_and_basic(self,p):
        _, column_status=self._get_basis(p)
        return [float(value) for value in p.getSolution()], [int(status)==1 for status in column_status]

    def get_feasibility_tolerance(self,p): return float(p.controls.feastol)

    def _canonical_bound(self,value):
        x=float(value); inf=float(self.xp.infinity)
        if x<=-inf: return -math.inf
        if x>=inf: return math.inf
        return x

    def extract_ebf_entries(self,p,*,tolerance=1e-9):
        vars_=list(p.getVariable()); cons=list(p.getConstraint()); values=list(p.getSolution())
        activities=list(self.xp.evaluate([c.getBody() for c in cons],problem=p)); row_status,col_status=self._get_basis(p)
        variables=[]
        for v,value,native in zip(vars_,values,col_status):
            value=float(value); lower=self._canonical_bound(v.lb); upper=self._canonical_bound(v.ub); bound=classify_bound_status(lower,upper,value,tolerance=tolerance)
            if native==1: bs=BasisStatus.BASIC
            elif native==3: bs=BasisStatus.SUPERBASIC
            elif native==0 and bound in {BoundStatus.INTERIOR,BoundStatus.FREE}: bs=BasisStatus.SUPERBASIC
            elif native in {0,2}: bs=BasisStatus.NONBASIC
            else: raise ValueError(f"Unknown Xpress column basis status {native} for {v.name}")
            variables.append(VariableBasisEntry(v.name,bs,bound,value,lower,upper))
        constraints=[]
        for c,activity,native in zip(cons,activities,row_status):
            activity=float(activity); lower=self._canonical_bound(c.lb); upper=self._canonical_bound(c.ub); bound=classify_bound_status(lower,upper,activity,tolerance=tolerance)
            if native==1: bs=BasisStatus.BASIC
            elif native==3: bs=BasisStatus.SUPERBASIC
            elif native in {0,2}: bs=BasisStatus.NONBASIC
            else: raise ValueError(f"Unknown Xpress row basis status {native} for {c.name}")
            constraints.append(ConstraintBasisEntry(c.name,bs,bound,activity,lower,upper))
        return variables,constraints

    def dispose(self,p):
        fn=getattr(p,"destroy",None)
        if callable(fn):
            try: fn()
            except Exception: pass
