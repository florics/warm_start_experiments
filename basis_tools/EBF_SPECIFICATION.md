# Explicit Basis Format (EBF) 1.1

## Variable file

```text
var_name,basis_status,bound_status,value
```

## Constraint file

```text
constr_name,basis_status,bound_status,activity
```

Rows are written sorted by entity name.

## `basis_status`

- `BASIC`
- `NONBASIC`
- `SUPERBASIC`

## `bound_status`

- `LOWER`
- `UPPER`
- `FIXED`
- `INTERIOR`
- `FREE`

For variables, `bound_status` refers to the variable's own bounds and value.
For constraints, it refers to row activity relative to the row lower and upper
bounds. In particular, it is not a direct copy of the solver-native row/slack
basis status.

Given row lower bound `L`, activity `a^T x` and upper bound `U`, the canonical
classification is:

1. `FIXED` if finite `L` and `U` coincide within the tolerance;
2. `FREE` if both bounds are infinite;
3. `LOWER` if activity is at `L` within the tolerance;
4. `UPPER` if activity is at `U` within the tolerance;
5. otherwise `INTERIOR`.

## Proper-simplex validation used for exchange bases

The experiment suite accepts an EBF as a portable proper simplex basis only if:

- the total number of `BASIC` entries across variables and constraints equals
  the number of model rows; and
- there are no `SUPERBASIC` entries.

The code does not implement EBF -> solver basis import. Solver-to-solver
transfer is performed through classical BAS files.
