#!/bin/bash
#SBATCH --job-name=rna_budcurve
#SBATCH --output=/path/to/RNA/logs/02c_budcurve_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:20:00
#SBATCH --exclude=c0706a-s23
set -uo pipefail
export TMPDIR=/tmp
cd /path/to/RNA || exit 1
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_eval || exit 2
for BM in v2 v1; do
  for CR in mfe umfe; do
    echo "################ $BM / $CR ################"
    python -I harness/koodli_budget_curve.py --engine vienna2 --bench $BM --criterion $CR \
        --out results/koodli_budget_curve_${BM}_${CR}.csv || exit 1
    echo
  done
done
