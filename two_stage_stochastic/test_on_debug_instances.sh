#!/bin/bash

exec > /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/results/debug/debug_instances_tests.log 2>&1

# copt, 3cm-br-ivm
python3 /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/run_correctness_test.py \
  copt \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged.lp \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged_electricity1p2.lp \
  /scratch/opt/lmehl/instances/2ssp/integrated/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged_plus_electricity1p2.lp \
  /scratch/htc/lmehl/master_thesis/base_problems/copt/parameters/dualsmplx_1Thrd.par \
  /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/results/debug/copt_3cm_br_ivm \
  --scenario-a base \
  --scenario-b electricity1p2

# copt, nomods
python3 /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/run_correctness_test.py \
  copt \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_nothingmodified.lp \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_nothingmodified_electricity1p2.lp \
  /scratch/opt/lmehl/instances/2ssp/integrated/debug/oemofB3_debug_nothingmodified_plus_electricity1p2.lp \
  /scratch/htc/lmehl/master_thesis/base_problems/copt/parameters/dualsmplx_1Thrd.par \
  /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/results/debug/copt_nomods \
  --scenario-a base \
  --scenario-b electricity1p2

# gurobi, 3cm-br-ivm
python3 /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/run_correctness_test.py \
  gurobi \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged.lp \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged_electricity1p2.lp \
  /scratch/opt/lmehl/instances/2ssp/integrated/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged_plus_electricity1p2.lp \
  /scratch/htc/lmehl/master_thesis/base_problems/gurobi/parameters/dualsmplx_1Thrd.prm \
  /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/results/debug/gurobi_3cm_br_ivm \
  --scenario-a base \
  --scenario-b electricity1p2

# gurobi, nomods
python3 /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/run_correctness_test.py \
  gurobi \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_nothingmodified.lp \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_nothingmodified_electricity1p2.lp \
  /scratch/opt/lmehl/instances/2ssp/integrated/debug/oemofB3_debug_nothingmodified_plus_electricity1p2.lp \
  /scratch/htc/lmehl/master_thesis/base_problems/gurobi/parameters/dualsmplx_1Thrd.prm \
  /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/results/debug/gurobi_nomods \
  --scenario-a base \
  --scenario-b electricity1p2

# highs, 3cm-br-ivm
python3 /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/run_correctness_test.py \
  highs \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged.lp \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged_electricity1p2.lp \
  /scratch/opt/lmehl/instances/2ssp/integrated/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged_plus_electricity1p2.lp \
  /scratch/htc/lmehl/master_thesis/base_problems/highs/parameters/dualsmplx_serial_1Thrd.txt \
  /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/results/debug/highs_3cm_br_ivm \
  --scenario-a base \
  --scenario-b electricity1p2

# highs, nomods
python3 /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/run_correctness_test.py \
  highs \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_nothingmodified.lp \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_nothingmodified_electricity1p2.lp \
  /scratch/opt/lmehl/instances/2ssp/integrated/debug/oemofB3_debug_nothingmodified_plus_electricity1p2.lp \
  /scratch/htc/lmehl/master_thesis/base_problems/highs/parameters/dualsmplx_serial_1Thrd.txt \
  /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/results/debug/highs_nomods \
  --scenario-a base \
  --scenario-b electricity1p2

# xpress, 3cm-br-ivm
python3 /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/run_correctness_test.py \
  xpress \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged.lp \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged_electricity1p2.lp \
  /scratch/opt/lmehl/instances/2ssp/integrated/debug/oemofB3_debug_3costmods_boundsremoved_investvarsmerged_plus_electricity1p2.lp \
  /scratch/htc/lmehl/master_thesis/base_problems/xpress/parameters/dualsmplx_1Thrd.prs \
  /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/results/debug/xpress_3cm_br_ivm \
  --scenario-a base \
  --scenario-b electricity1p2

# xpress, nomods
python3 /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/run_correctness_test.py \
  xpress \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_nothingmodified.lp \
  /scratch/opt/lmehl/instances/2ssp/single_scenarios/debug/oemofB3_debug_nothingmodified_electricity1p2.lp \
  /scratch/opt/lmehl/instances/2ssp/integrated/debug/oemofB3_debug_nothingmodified_plus_electricity1p2.lp \
  /scratch/htc/lmehl/master_thesis/base_problems/xpress/parameters/dualsmplx_1Thrd.prs \
  /scratch/htc/lmehl/master_thesis/warm_start_experiments/two_stage_stochastic/results/debug/xpress_nomods \
  --scenario-a base \
  --scenario-b electricity1p2
