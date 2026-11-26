#!/bin/bash
#SBATCH --job-name=rna_cost
#SBATCH --output=/path/to/RNA/logs/34_cost_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:15:00
#SBATCH --exclude=c0706a-s23
set -uo pipefail
export TMPDIR=/tmp
cd /path/to/RNA || exit 1
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_eval || exit 2
for H in 0.25 1 6 24; do
  echo "################ B_max = $H 小时/题/seed ################"
  python -I harness/campaign_cost.py --seeds 5 --bmax-hours $H || exit 1
  echo
done
