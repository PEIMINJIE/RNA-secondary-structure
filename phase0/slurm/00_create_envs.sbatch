#!/bin/bash
#SBATCH --job-name=rna_envs
#SBATCH --output=/path/to/RNA/logs/00_create_envs_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --exclude=c0706a-s23

set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1

echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} start=$(date)"

# 计算节点出网探测：失败就直接退，不要静默卡住
if ! curl -fsS --max-time 20 -o /dev/null https://conda.anaconda.org/conda-forge/noarch/repodata.json; then
  echo "FATAL: 计算节点无法访问 conda-forge（需改用登录节点安装）"
  exit 2
fi
echo "网络 OK"

LOG=$ROOT/logs/create_envs_${SLURM_JOB_ID:-manual}.log bash env/create_envs.sh
rc=$?
echo "create_envs rc=$rc end=$(date)"
exit $rc
