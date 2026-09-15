# Two-Stage Stochastic Warm Starts

`construct_two_stage_basis.py` builds a classical MPS BAS file for an
integrated two-stage LP with two or more scenarios. It validates every source
BAS file against its source LP names, applies the integrated-LP scenario naming
convention, and makes every generated non-anticipativity row BASIC.

The command requires source bases generated for the same solver as the target
solve. The solver adapters handle the existing HiGHS native BAS conversion
when those source bases are generated through `generate_solver_bases.py`.

Construct and validate only:

```bash
python3 two_stage_stochastic/construct_two_stage_basis.py \
  gurobi scenario_a.lp scenario_a.bas scenario_b.lp scenario_b.bas \
  integrated.lp --output-parent results/two_stage_debug \
  --scenario-a base --scenario-b electricity1p2
```

Load and solve with an external dual-simplex parameter file:

```bash
python3 two_stage_stochastic/construct_two_stage_basis.py \
  gurobi scenario_a.lp scenario_a.bas scenario_b.lp scenario_b.bas \
  integrated.lp --output-parent results/two_stage_debug --run-label gurobi_debug \
  --scenario-a base --scenario-b electricity1p2 \
  --parameter-file dual_simplex_no_presolve.prm --solve
```

Alternatively, supply the LPs, source bases, and scenario names in a one-row
CSV and omit all five positional paths and both scenario flags:

```csv
integrated_lp,first_lp,first_bas,first_scenarioname,second_lp,second_bas,second_scenarioname
integrated.lp.gz,first.lp,first.bas.gz,base,second.lp.gz,second.bas.gz,electricity1p2
```

```bash
python3 two_stage_stochastic/construct_two_stage_basis.py \
  gurobi --input-csv experiment.csv --output-parent results/two_stage_debug \
  --parameter-file dualsmplx_1Thrd.prm --solve
```

Relative LP and BAS paths resolve from the CSV directory. Explicit
`--scenario-a` or `--scenario-b` values override the corresponding CSV value.

For more than two scenarios, repeat `--scenario NAME LP BAS` and provide the
integrated LP separately. The first scenario is the default non-anticipativity
reference; `--reference-scenario` selects another input scenario. Each
investment variable receives one row between the reference and every other
scenario, avoiding redundant all-pairs rows.

```bash
python3 two_stage_stochastic/construct_two_stage_basis.py \
  gurobi --integrated-lp integrated.lp.gz --output-parent results/two_stage_debug \
  --scenario base base.lp.gz base.bas.gz \
  --scenario electricity1p2 electricity.lp.gz electricity.bas.gz \
  --scenario heat1p2 heat.lp.gz heat.bas.gz \
  --reference-scenario base --parameter-file dualsmplx_1Thrd.prm --solve
```

The equivalent multi-scenario CSV has one row per source scenario:

```csv
integrated_lp,lp,bas,scenarioname
integrated.lp.gz,base.lp.gz,base.bas.gz,base
integrated.lp.gz,electricity.lp.gz,electricity.bas.gz,electricity1p2
integrated.lp.gz,heat.lp.gz,heat.bas.gz,heat1p2
```

The constructor creates
`run_<integrated-instance-stem>_<solver>_<YYYY-MM-DD_HH-MM-SS>[_<label>]`
below `--output-parent`. The instance stem strips `.lp` and an optional `.gz`
suffix. Each directory contains the constructed BAS, JSON report, and, when
`--solve` is used, the solver log. If a timestamp collision occurs, it waits a
random whole-second delay from 1 through 60, then retries.

All constructor-written basis artifacts are gzip-compressed. A successful
`--solve` writes `integrated_warmstart.bas.gz`, `optimal_basis.bas.gz`, and
the optimal EBF pair `optimal_basis__vars.csv.gz` and
`optimal_basis__constrs.csv.gz`. It also writes `optimal_solution.sol.gz` for
Gurobi, COPT, and HiGHS. Xpress writes `optimal_solution.sol.zip`, containing
its native `.asc` and `.hdr` files. The JSON report records all artifact paths
and the first, second, and integrated LP paths.

Use `--repetitions N` with either driver to perform `N` fresh integrated
warm-start solves using the same constructed BAS. Each repetition reloads the
integrated LP, reapplies parameters, reloads the BAS, and writes its own solver
log. The report records every result and min/median/max timing and iteration
statistics. Optimal artifacts are written only for the first optimal
repetition. Each repetition is measured by default with `/usr/bin/time -v perf
stat -e cycles,instructions,task-clock,cpu-clock`; if `perf` is unavailable,
only `/usr/bin/time -v` is used. Pass `--no-measure` to opt out.

For normal tests and experiments, use the standard external dual-simplex
parameter file and leave presolve at the solver default. The driver never
changes presolve itself. The dedicated `*_no_presolve` parameter files are an
optional diagnostic mode for isolating a basis-loading or presolve interaction.

The current driver fails before optimization if a source BAS cannot be parsed,
scenario model names differ, the merged names/order do not match the integrated
LP, or a coupling row is not BASIC after the solver reads the BAS.

For a full solver correctness run, use `run_correctness_test.py`. It reuses the
existing source-basis generator, then invokes the constructor and optional
warm-start solve:

```bash
python3 two_stage_stochastic/run_correctness_test.py \
  gurobi scenario_a.lp scenario_b.lp integrated.lp \
  dualsmplx_1Thrd_no_presolve.prm results/two_stage_debug \
  --scenario-a base --scenario-b electricity1p2 --measure
```

`--measure` wraps the source-basis generation and integrated warm-start process
separately in `/usr/bin/time -v perf stat -e cycles,instructions,task-clock,cpu-clock`.
If `perf` is unavailable, it warns and collects `/usr/bin/time -v` only.
Use `--no-solve` to validate construction and basis import prerequisites only.

The integrated solve records iteration-zero dual-feasibility evidence from its
solver log by default. Disable only this diagnostic with
`--no-check-initial-dual-feasibility` on `run_correctness_test.py`.
For HiGHS, the diagnostic additionally runs a zero-iteration, presolve-off
probe and records its native dual-infeasibility statistics before reloading the
original BAS for the actual solve.
