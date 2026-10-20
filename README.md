# Shared simplex-basis tools and experiments

This directory is the cleaned-up replacement for the three previously separate
basis-related code trees. The experiment logic remains separate, but all
solver-specific basis handling now has one implementation.

```text
warm_start_experiments/
├── basis_tools/
│   ├── ebf.py
│   ├── mps_bas.py
│   ├── io_utils.py
│   ├── basis_export.py
│   ├── compare_ebf.py
│   ├── solver_adapters/
│   │   ├── gurobi_adapter.py
│   │   ├── copt_adapter.py
│   │   ├── highs_adapter.py
│   │   └── xpress_adapter.py
│   └── tests/
│       ├── cross_solver_basis_test.py
│       ├── test_compressed_io.py
│       ├── test_ebf_core.py
│       └── test_mps_bas.py
├── generate_solver_bases/
│   ├── generate_bases.py
│   └── examples/
└── scenario_catalogue_warmstart/
    ├── warmstart_batch.py
    └── examples/
```

## What was consolidated

There is now exactly one implementation of:

- Explicit Basis Format (EBF 1.1): `basis_tools/ebf.py`
- classical MPS/CPLEX-style BAS parsing/writing and the HiGHS native-basis
  converter: `basis_tools/mps_bas.py`
- each solver adapter: `basis_tools/solver_adapters/`
- EBF extraction + proper-simplex validation: `basis_tools/basis_export.py`
- compressed LP/BAS/EBF I/O: `basis_tools/io_utils.py`

The three workflows remain separate:

- `generate_solver_bases/generate_bases.py`: solve LPs and generate bases.
- `scenario_catalogue_warmstart/warmstart_batch.py`: run the dual-simplex warm-start
  timing experiments.
- `basis_tools/tests/cross_solver_basis_test.py`: diagnostic cross-solver basis
  portability test.

The cross-solver test therefore exercises the same adapters used by the actual
experiments and basis generation.

## Compression

### Reading

LP, BAS and EBF inputs support:

- plain files (`model.lp`, `basis.bas`, `vars.csv`)
- gzip (`model.lp.gz`, `basis.bas.gz`, `vars.csv.gz`)
- ZIP archives containing exactly one non-directory file.

For ZIP, both `model.lp.zip` and a generic archive name such as `model.zip` are
accepted as long as the single member has the required extension. This
single-member rule prevents ambiguous solver input selection.

### Writing

Generated BAS and EBF files can be plain or gzip-compressed. Both experiment
runners use gzip-compressed output by default. Pass:

```bash
--no-compress-output
```

to write plain `.bas` and EBF `.csv` artifacts instead.

ZIP output is intentionally not implemented.

## EBF semantics

Variables:

```text
var_name,basis_status,bound_status,value
```

Constraints:

```text
constr_name,basis_status,bound_status,activity
```

`basis_status` is one of `BASIC`, `NONBASIC`, `SUPERBASIC`.
`bound_status` is one of `LOWER`, `UPPER`, `FIXED`, `INTERIOR`, `FREE`.

For constraints, `bound_status` is always classified from the actual row
activity and row lower/upper bounds. It is not copied from a solver-native row
or slack status.

A portable proper simplex basis must have exactly as many BASIC entries across
variables and row variables as there are model rows, and must have no
SUPERBASIC entries.

## HiGHS basis handling

HiGHS basis input accepts either:

- native text beginning with `HiGHS_basis_file`, or
- classical BAS beginning with `NAME`.

Normal experiment output is always a classical `.bas` exchange basis. HiGHS
first writes its native basis text and that text is converted through
`basis_tools.mps_bas`.

The cross-solver diagnostic additionally stores the producer's native basis,
which for HiGHS is named with `.highs.bas` (or `.highs.bas.gz`).

## Running the tests

Solver-independent tests:

```bash
cd /path/to/warm_start_experiments
python -m unittest discover -s basis_tools/tests -p 'test_*.py' -v
```

Cross-solver integration test, for example:

```bash
python basis_tools/tests/cross_solver_basis_test.py \
    /path/to/debug.lp.gz \
    --out /path/to/test_results \
    --solvers gurobi copt highs xpress \
    --producer-param gurobi=/path/to/barrier_with_crossover.prm \
    --consumer-param gurobi=/path/to/dual_simplex.prm \
    --consumer-param copt=/path/to/dual_simplex.par \
    --consumer-param highs=/path/to/dual_simplex.options \
    --consumer-param xpress=/path/to/dual_simplex.prs
```

example
```bash
python basis_tools/tests/cross_solver_basis_test.py \
    /scratch/opt/lmehl/instances/base/2050-100-el_eff-3costmods-1e9boundsremoved-investvarsmerged.lp \
    --out results/tests/ \
    --solvers gurobi copt xpress highs \
    --producer-param gurobi=/scratch/htc/lmehl/master_thesis/base_problems/gurobi/parameters/barrier_wCrssvr_8Thrds.prm \
    --consumer-param gurobi=/scratch/htc/lmehl/master_thesis/base_problems/gurobi/parameters/dualsmplx_1Thrd.prm \
    --consumer-param copt=/scratch/htc/lmehl/master_thesis/base_problems/copt/parameters/dualsmplx_1Thrd.par \
    --consumer-param highs=/scratch/htc/lmehl/master_thesis/base_problems/highs/parameters/dualsmplx_serial_1Thrd.txt \
    --consumer-param xpress=/scratch/htc/lmehl/master_thesis/base_problems/xpress/parameters/dualsmplx_1Thrd.prs
```

Pass `--no-compress-output` if the generated basis/EBF diagnostics should be
written as plain files.

## Direct imports

The runners add their parent project directory to `sys.path`, so the shown
layout can be used directly without installing a Python package. If you move a
runner elsewhere, put the directory containing `basis_tools/` on `PYTHONPATH`.
