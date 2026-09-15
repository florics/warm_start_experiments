# Stepwise Two-Stage Warm Starts

`stepwise_two_stage.py` starts from the integrated two-stage LP, removes all
named non-anticipativity rows in memory, installs the combined uncoupled basis,
and solves that uncoupled model once. It then adds satisfied coupling rows in a
batch and one dynamically selected violated row at a time, reoptimizing the
same model object with the configured dual-simplex parameters.

```bash
python3 stepwise_two_stage.py \
  gurobi scenario_a.lp scenario_a.bas scenario_b.lp scenario_b.bas integrated.lp.gz \
  --output-parent results --scenario-a base --scenario-b electricity1p01 \
  --parameter-file dualsmplx_1Thrd.prm --strategy relative_descending \
  --repetitions 3
```

The five positional LP/BAS paths and both scenario flags may be replaced by a
one-row CSV:

```csv
integrated_lp,first_lp,first_bas,first_scenarioname,second_lp,second_bas,second_scenarioname
integrated.lp.gz,first.lp,first.bas.gz,base,second.lp.gz,second.bas.gz,electricity1p01
```

```bash
python3 stepwise_two_stage.py gurobi --input-csv experiment.csv \
  --output-parent results --parameter-file dualsmplx_1Thrd.prm
```

CSV-relative paths resolve from the CSV directory. Explicit scenario flags
override their CSV values.

For an LP with more than two scenarios, use the same repeated `--scenario NAME
LP BAS` and `--integrated-lp` form as the all-at-once constructor. Coupling rows
form a reference star: each investment variable is coupled from the first input
scenario, or the scenario named by `--reference-scenario`, to every other
scenario. The multi-scenario CSV schema is `integrated_lp,lp,bas,scenarioname`,
with one row per source scenario.

```bash
python3 stepwise_two_stage.py gurobi \
  --integrated-lp integrated.lp.gz --output-parent results \
  --scenario base base.lp.gz base.bas.gz \
  --scenario electricity1p2 electricity.lp.gz electricity.bas.gz \
  --scenario heat1p2 heat.lp.gz heat.bas.gz \
  --reference-scenario base --parameter-file dualsmplx_1Thrd.prm
```

Strategies are `relative_ascending`, `relative_descending`, `random`, and
`all_at_once`. Use `--random-seed` to reproduce random ordering. Repetitions
are measured independently with `/usr/bin/time -v perf stat` by default;
`--no-measure` disables the external wrapper.

Each run directory contains `uncoupled_warmstart.bas.gz`, a per-repetition
solver log, `repetition_XXX.steps.csv`, worker configuration/results, and
`stepwise_report.json`. The CSV records the chosen row, current variable values
and basis status, disagreement metrics, rows added as already satisfied,
per-step solve metrics, and before/after remaining-violation summaries.

The first optimal repetition that adds every coupling and leaves no residual
larger than the solver feasibility tolerance writes the final compressed BAS,
EBF, and solution artifacts using the shared adapter infrastructure.

Solver-specific row insertion is implemented in the shared adapters. It must
be validated with licensed cluster runs for COPT and Xpress, whose Python row
deletion APIs are version-sensitive.
