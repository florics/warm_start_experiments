# Generate solver bases

For every instance and every solver/parameter configuration, the runner loads a
fresh LP, applies the supplied parameter file, solves, exports EBF 1.1, checks
that the state is a proper simplex basis, and writes a classical `.bas` file.

```bash
python generate_solver_bases/generate_bases.py \
    generate_solver_bases/examples/instances.csv \
    generate_solver_bases/examples/solver_parameters.csv \
    /path/to/results
```

Add `--compress-output` to store the generated basis and EBF artifacts as
`.bas.gz` and `.csv.gz`. The default is compressed output.

`instances.csv`:

```text
name,lp_file
```

LP inputs may be `.lp`, `.lp.gz`, or a single-member ZIP containing an `.lp`
file.

`solver_parameters.csv`:

```text
solver,parameter_name,parameter_file
```

Supported solver keys are `gurobi`, `copt`, `highs`, and `xpress`.

The EBF files are intentionally written before the proper-simplex validation.
Thus, if validation fails, the diagnostic EBF files remain available, no BAS is
written, and the result is `INVALID_SIMPLEX_BASIS`.

## Output and result codes

Each invocation creates:

```text
RESULTS_DIR/
└── run_YYYY-MM-DD_HH-MM-SS/
    ├── summary.csv
    ├── experiment_info.txt
    ├── input_instances.csv
    ├── input_solver_parameters.csv
    ├── parameters/
    ├── logs/
    ├── bases/
    └── explicit_bases/
```

Result codes are preserved from the previous generator:

- `OK`: optimal solve, valid portable simplex EBF, BAS written;
- `NONOPTIMAL`: solve did not finish optimally;
- `INVALID_SIMPLEX_BASIS`: EBF was retained for diagnosis, BAS was not written;
- `BASIS_WRITE_ERROR`: EBF is valid but the classical BAS could not be written;
- `ERROR`: another exception occurred.

Exit status is `0` if all combinations return `OK`, `1` for preflight/setup
failure, and `2` if the batch completes with at least one failed combination.
The generator performs the same all-requested-solvers import preflight before it
creates the run directory.

For Xpress, `examples/xpress_example.prs` shows the simple `CONTROL=VALUE`
syntax accepted by the shared adapter.
