#!/bin/bash
#SBATCH --job-name=rna_reverify
#SBATCH --output=/path/to/RNA/logs/02b_reverify_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=03:00:00
#SBATCH --exclude=c0706a-s23

# 第一轮汇总把 V1/V2 和 vienna1/vienna2 混在一起了（verify.py 没把 benchmarks/gen_engine 带下去）。
# 这里重验证 + 按 (方法, 变体, 生成引擎, benchmark) 正确分组。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_eval || exit 2

echo "=== 重建 benchmark（含 id-less 来源的内容比对修正）==="
python -I harness/build_benchmarks.py || exit 1

echo "=== 重验证 3270 条 ==="
python -I harness/verify.py --in data/koodli/designs.jsonl \
    --out results/koodli_verified.jsonl \
    --provenance results/koodli_provenance.json || exit 1

echo "=== 正确分组汇总 ==="
python -I harness/summarize.py --in results/koodli_verified.jsonl \
    --out results/koodli_summary.csv --group method,variant,gen_engine || exit 1
echo "end=$(date)"
