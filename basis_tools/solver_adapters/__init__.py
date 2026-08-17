"""Lazy factory for the shared solver adapters."""

SUPPORTED_SOLVERS = ("gurobi", "copt", "highs", "xpress")


def get_solver_adapter(name: str):
    key = name.strip().lower()
    if key == "gurobi":
        from .gurobi_adapter import GurobiAdapter
        return GurobiAdapter()
    if key == "copt":
        from .copt_adapter import CoptAdapter
        return CoptAdapter()
    if key == "highs":
        from .highs_adapter import HighsAdapter
        return HighsAdapter()
    if key == "xpress":
        from .xpress_adapter import XpressAdapter
        return XpressAdapter()
    raise ValueError(f"Unknown solver {name!r}. Supported: {', '.join(SUPPORTED_SOLVERS)}")


# Compatibility name used by the cross-read test's older revisions.
get_basis_adapter = get_solver_adapter
