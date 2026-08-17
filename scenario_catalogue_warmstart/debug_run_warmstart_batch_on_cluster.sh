#!/bin/bash

#SBATCH --job-name=mthesis_scencat_warmstarts
#output paths have to adjusted to your folders
#SBATCH --output=/scratch/htc/lmehl/master_thesis/warm_start_experiments/results/tests/scenario_catalogue_warmstart/job_out/sbatch_job_%A.out
#SBATCH --error=/scratch/htc/lmehl/master_thesis/warm_start_experiments/results/tests/scenario_catalogue_warmstart/job_out/sbatch_job_%A.err
#SBATCH --partition=big
#SBATCH --time=10:00:00
#SBATCH --mem=10G
#SBATCH --cpus-per-task=1
#SBATCH --exclude=htc-gpu[001-115]

#for usage at z1 cluster set http and https proxy environment variables
export https_proxy=http://squid.zib.de:3128
export http_proxy=http://squid.zib.de:3128 

export COPT_HOME=/software/COPT/copt80
export COPT_LICENSE_DIR=/software/COPT/copt80/ziblic/
export PATH=$COPT_HOME/bin:$PATH
#export DYLD_LIBRARY_PATH=$COPT_HOME/lib:$DYLD_LIBRARY_PATH
export LD_LIBRARY_PATH=$COPT_HOME/lib:$LD_LIBRARY_PATH

export GUROBI_HOME="/software/Gurobi/gurobi1300/linux64"
export PATH="${PATH}:${GUROBI_HOME}/bin"
if [ -z "$LD_LIBRARY_PATH" ]
then
    export LD_LIBRARY_PATH="${GUROBI_HOME}/lib"
else
    export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:${GUROBI_HOME}/lib"
fi
export GRB_LICENSE_FILE=/software/Gurobi/gurobi1300/gurobi.lic

export XPAUTH_PATH=/software/opt-sw/xpress_licence/xpauth_31-mar-2030_9.8.xpr

echo "------ SLURM allocation info ------"
echo "Job ID: ${SLURM_JOB_ID:-unknown}"
echo "Allocated node(s): ${SLURM_JOB_NODELIST:-unknown}"
echo "CPUs per task: ${SLURM_CPUS_PER_TASK:-not explicitly set}"
echo "CPUs allocated on node: ${SLURM_CPUS_ON_NODE:-unknown}"

echo "Batch-shell CPU affinity:"
taskset -cp $$ || true

echo "SLURM job information:"
scontrol show job "$SLURM_JOB_ID" | grep -E \
    'JobId=|NodeList=|NumNodes=|NumCPUs=|ReqTRES=|AllocTRES=|ReqS:C:T=|ReqB:S:C:T=' \
    || true

echo "Actual task affinity using srun:"
srun --cpu-bind=quiet bash -c '
    echo "Task PID: $$"
    taskset -cp $$
    echo "CPU/core mapping:"
    ALLOWED_CPUS=$(taskset -pc $$ | awk -F": " "{print \$2}")
    lscpu -p=CPU,CORE,SOCKET,NODE | grep -v "^#" |
    awk -F, -v allowed="$ALLOWED_CPUS" "
    BEGIN {
        n = split(allowed, ranges, \",\")
        for (i = 1; i <= n; i++) {
            if (ranges[i] ~ /-/) {
                split(ranges[i], r, \"-\")
                for (j = r[1]; j <= r[2]; j++)
                    a[j] = 1
            } else {
                a[ranges[i]] = 1
            }
        }
    }
    a[\$1] {
        printf \"CPU %-4s CORE %-4s SOCKET %-2s NUMA %-2s\n\", \$1, \$2, \$3, \$4
    }"
'

echo "CPU frequency SBATCH setting:"
grep -E '^#SBATCH[[:space:]]+--cpu-freq(=|[[:space:]])' "$0" \
    || echo "#SBATCH --cpu-freq: not set"

echo "SLURM CPU frequency request: ${SLURM_CPU_FREQ_REQ:-not reported}"

echo "SBATCH hint setting:"
grep -E '^#SBATCH[[:space:]]+--hint(=|[[:space:]])' "$0" \
    || echo "#SBATCH --hint: not set"

echo "Requested memory per node: \
$((SLURM_MEM_PER_NODE / 1024)) GiB \
($(awk -v m="$SLURM_MEM_PER_NODE" \
'BEGIN { printf "%.2f", m*1024*1024/1e9 }') GB)"

echo "------ (end of SLURM allocation info) ------"

echo "------ Hardware info: ------"
lscpu
echo "------ (end of hardware info) ------"

source ~/conda_init

# for copt
python /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/warmstart_batch.py \
    copt \
    /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/csvs-for-arguments/debug/debug_instances.csv \
    1 \
    /scratch/htc/lmehl/master_thesis/base_problems/copt/parameters/dualsmplx_1Thrd.par \
    /scratch/htc/lmehl/master_thesis/warm_start_experiments/results/tests/scenario_catalogue_warmstart \
    --experiments-csv /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/csvs-for-arguments/debug/debug_experiments.csv

sleep 5

# for gurobi
python /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/warmstart_batch.py \
    gurobi \
    /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/csvs-for-arguments/debug/debug_instances.csv \
    1 \
    /scratch/htc/lmehl/master_thesis/base_problems/gurobi/parameters/dualsmplx_1Thrd.prm \
    /scratch/htc/lmehl/master_thesis/warm_start_experiments/results/tests/scenario_catalogue_warmstart \
    --experiments-csv /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/csvs-for-arguments/debug/debug_experiments.csv

sleep 5

# for highs
python /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/warmstart_batch.py \
    highs \
    /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/csvs-for-arguments/debug/debug_instances.csv \
    1 \
    /scratch/htc/lmehl/master_thesis/base_problems/highs/parameters/dualsmplx_serial_1Thrd.txt \
    /scratch/htc/lmehl/master_thesis/warm_start_experiments/results/tests/scenario_catalogue_warmstart \
    --experiments-csv /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/csvs-for-arguments/debug/debug_experiments.csv

sleep 5

# for xpress
python /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/warmstart_batch.py \
    xpress \
    /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/csvs-for-arguments/debug/debug_instances.csv \
    1 \
    /scratch/htc/lmehl/master_thesis/base_problems/xpress/parameters/dualsmplx_1Thrd.prs \
    /scratch/htc/lmehl/master_thesis/warm_start_experiments/results/tests/scenario_catalogue_warmstart \
    --experiments-csv /scratch/htc/lmehl/master_thesis/warm_start_experiments/scenario_catalogue_warmstart/csvs-for-arguments/debug/debug_experiments.csv
