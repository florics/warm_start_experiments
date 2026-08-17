# `basis_tools`

Shared basis infrastructure for Gurobi, COPT, HiGHS and Xpress.

- `ebf.py`: EBF 1.1 schema, read/write, validation and comparisons.
- `mps_bas.py`: classical BAS parser/writer and HiGHS native-text converter.
- `io_utils.py`: plain/gzip/ZIP input and plain/gzip output helpers.
- `basis_export.py`: common solver -> EBF extraction/write/validation.
- `solver_adapters/`: one implementation per solver.
- `tests/cross_solver_basis_test.py`: integration test for cross-solver BAS
  transfer using the shared adapters.

## Standalone HiGHS conversion

```bash
python -m basis_tools.mps_bas highs-to-bas input.highs.bas output.bas
```

Compressed files work as well, for example:

```bash
python -m basis_tools.mps_bas highs-to-bas input.highs.bas.gz output.bas.gz
```

## EBF comparison

One EBF file:

```bash
python basis_tools/compare_ebf.py file first.csv second.csv.gz --tolerance 1e-9
```

Complete basis:

```bash
python basis_tools/compare_ebf.py basis \
    first__vars.csv first__constrs.csv \
    second__vars.csv.gz second__constrs.csv.gz \
    --tolerance 1e-9
```
