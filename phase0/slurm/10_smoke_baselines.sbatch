#!/bin/bash
#SBATCH --job-name=rna_bl_smoke
#SBATCH --output=/path/to/RNA/logs/10_bl_smoke_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --exclude=c0706a-s23

# A 类 baseline 的「能跑起来 + 调用能被计数」冒烟测试（只用最小的几道题）。
# 不是正式评测：正式 solved@B 曲线要等用户确认预算与 seed 数后再提交。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
OUT=$ROOT/results/smoke
cd "$ROOT" || exit 1
mkdir -p "$OUT"

echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

echo "=============== 1. RNAinverse-pf（统一环境 2.8.0）==============="
conda activate rnad_eval || exit 2
python -c "import RNA; print('ViennaRNA', RNA.__version__)"
python -I harness/run_rnainverse.py \
    --bench data/eterna100/eterna100_v2.jsonl \
    --out "$OUT/rnainverse_pf_smoke.jsonl" \
    --mode pf --budget 2000 --seed 0 --ids 1,8,23
echo "rc=$?"
python -I harness/verify.py --in "$OUT/rnainverse_pf_smoke.jsonl" \
    --out "$OUT/rnainverse_pf_smoke.verified.jsonl"

echo "=============== 2. SAMFEO（生成侧 2.6.4 + 调用计数）==============="
conda deactivate
conda activate rnad_samfeo || exit 2
python -c "import RNA; print('ViennaRNA', RNA.__version__)"
for S in "(((((......)))))" "((....)).((....))"; do
  echo "--- 目标 $S ---"
  echo "$S" | timeout 1200 python -I harness/run_counted.py \
      --counts "$OUT/samfeo_counts_L${#S}.json" \
      --cwd "$OUT" \
      --tag "samfeo_smoke" \
      -- "$ROOT/third_party/samfeo/main.py" --online --step 100
  echo "rc=$?"
done
echo "--- SAMFEO 计数文件 ---"
for f in "$OUT"/samfeo_counts_*.json; do echo "## $f"; python -c "
import json,sys; d=json.load(open('$f')); print(' counts:', d.get('counts')); print(' wall:', d.get('wall_sec'))
"; done

echo "=============== 3. NEMO（Turner 2004，计数器版）==============="
if [ -x "$ROOT/build/nemo_bin" ]; then
  export NEMO_COUNT_FILE=$OUT/nemo_counts.jsonl
  : > "$NEMO_COUNT_FILE"
  for S in "(((((......)))))" "((....)).((....))"; do
    echo "--- 目标 $S ---"
    (cd "$(dirname "$(readlink -f "$ROOT/build/nemo_bin")")" && timeout 1200 ./nemo -i 300 "$S")
    echo "rc=$?"
  done
  echo "--- NEMO 计数 ---"; cat "$NEMO_COUNT_FILE"
else
  echo "SKIP: build/nemo_bin 不存在（01_build_nemo 还没成功）"
fi

echo "end=$(date)"
