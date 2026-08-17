# Warm-start experiments

Run one solver at a time:

```bash
python scenario_catalogue_warmstart/warmstart_batch.py \
    gurobi \
    scenario_catalogue_warmstart/examples/data.csv \
    3 \
    /path/to/dual_simplex.prm \
    /path/to/results \
    --experiments-csv scenario_catalogue_warmstart/examples/experiments.csv
```

Or run all ordered target/source combinations:

```bash
python scenario_catalogue_warmstart/warmstart_batch.py \
    highs data.csv 3 dual_simplex.options /path/to/results \
    --all-experiments
```

Add `--compress-output` to write the repetition-1 optimal basis and EBF files
as `.bas.gz` / `.csv.gz`.

The data CSV has columns:

```text
name,lp_file,basis_file,basis_description
```

`lp_file` may be plain, gzip, or a single-member ZIP containing an `.lp` file.
`basis_file` may be plain, gzip, or a single-member ZIP containing a `.bas`
file.

The experiments CSV has columns:

```text
instance_name,basis_name
```

Each repetition reloads both the target LP and warm-start basis from disk. A
basis read failure is recorded as `BASIS_READ_ERROR` and optimization is not
started. The resulting optimal basis and EBF are written only for repetition 1,
matching the previous behavior.

For Xpress, `examples/xpress_parameters.prs` shows the control-file syntax used
by the shared adapter. The warm-start runner validates `LPFLAGS=1` (dual
simplex), as before.
