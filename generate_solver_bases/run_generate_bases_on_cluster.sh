#!/bin/bash

#SBATCH --job-name=mthesis_compute_sbases
#output paths have to adjusted to your folders
#SBATCH --output=/scratch/htc/lmehl/master_thesis/warm_start_experiments/results/generate_solver_bases/job_out/sbatch_job_%A.out
#SBATCH --error=/scratch/htc/lmehl/master_thesis/warm_start_experiments/results/generate_solver_bases/job_out/sbatch_job_%A.err
#SBATCH --partition=big
#SBATCH --time=10:00:00
#SBATCH --mem=10G
#SBATCH --cpus-per-task=16
#SBATCH --hint=nomultithread
#SBATCH --cpu-freq=medium-medium:Performance
#SBATCH --constraint=Gold6338
#SBATCH --exclude=htc-gpu[001-115],htc-cmp[101-102],htc-cmp104,htc-cmp126,htc-cmp[145-148]
#SBATCH --nodelist=htc-cmp132

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

python /scratch/htc/lmehl/master_thesis/generate_solver_bases/generate_bases.py "$@"

#python /scratch/htc/lmehl/master_thesis/generate_solver_bases/generate_bases.py  /scratch/htc/lmehl/master_thesis/generate_solver_bases/examples/instances.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/examples/solver_parameters_16Thrds.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/output/

# usage / todos

# sbatch /scratch/htc/lmehl/master_thesis/generate_solver_bases/run_on_cluster.sh /scratch/htc/lmehl/master_thesis/generate_solver_bases/instance_csvs/nomods_d1p00-1p05_instances.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/parameter_csvs/simplex_copt-gurobi-highs.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/output/

# sbatch /scratch/htc/lmehl/master_thesis/generate_solver_bases/run_on_cluster.sh /scratch/htc/lmehl/master_thesis/generate_solver_bases/instance_csvs/3cm-br-ivm_d1p00-1p05_instances.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/parameter_csvs/simplex_copt-gurobi-highs.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/output/

# sbatch --cpus-per-task=16 /scratch/htc/lmehl/master_thesis/generate_solver_bases/run_on_cluster.sh /scratch/htc/lmehl/master_thesis/generate_solver_bases/instance_csvs/nomods_d1p00-1p05_instances.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/parameter_csvs/copt_barrier_16Thrds.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/output/

# sbatch --cpus-per-task=16 /scratch/htc/lmehl/master_thesis/generate_solver_bases/run_on_cluster.sh /scratch/htc/lmehl/master_thesis/generate_solver_bases/instance_csvs/3cm-br-ivm_d1p00-1p05_instances.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/parameter_csvs/xpress_barrier_16Thrds.csv /scratch/htc/lmehl/master_thesis/generate_solver_bases/output/
