#!/bin/bash
#SBATCH --job-name=rna_camp
#SBATCH --output=/path/to/RNA/logs/42_camp_%A_%a.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=08:00:00
#SBATCH --array=0-24
#SBATCH --exclude=c0706a-s23

# Phase 0 正式 campaign（baseline_plan.md §7 第 3 步）：
#   折叠调用预算 B_max = 1e5，墙钟双闸 900 s，5 seeds，Eterna100-V2 全 100 题
#   array = 5 seeds × 5 个 20 题的分块；每块串行跑，单核 2 G（按实测峰值 3-82 MB 给的）
# METHOD 由 --export 传入（先 export 再 --export=ALL，不要把逗号列表塞进 --export）
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
METHOD=${METHOD:-nemo}
FOLD_BUDGET=${FOLD_BUDGET:-100000}
TIME_LIMIT=${TIME_LIMIT:-900}

SEED=$(( SLURM_ARRAY_TASK_ID / 5 ))
CHUNK=$(( SLURM_ARRAY_TASK_ID % 5 ))
OUT=$ROOT/results/solvedB/${METHOD}_v2_B${FOLD_BUDGET}
mkdir -p "$OUT"

IDS=$(python3 -c "
import json
rows=[json.loads(l) for l in open('$ROOT/data/eterna100/eterna100_v2.jsonl')]
ids=sorted(r['id'] for r in rows)
print(','.join(str(i) for i in ids[$CHUNK*20:($CHUNK+1)*20]))
")
echo "host=$(hostname) method=$METHOD seed=$SEED chunk=$CHUNK B=$FOLD_BUDGET T=$TIME_LIMIT"
echo "题号: $IDS"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
case "$METHOD" in
  nemo|rnainverse) conda activate rnad_eval    || exit 2 ;;
  samfeo)          conda activate rnad_samfeo  || exit 2 ;;
  desirna)         conda activate rnad_eval    || exit 2 ;;   # 退路：DesiRNA 只多一个 multiprocess 依赖
  samplingdesign)  conda activate rnad_sd      || exit 2 ;;
  *) echo "未知 METHOD"; exit 3 ;;
esac

python -u -I harness/run_campaign.py --method "$METHOD" --bench v2 --seed "$SEED" \
    --fold-budget "$FOLD_BUDGET" --time-limit "$TIME_LIMIT" --ids "$IDS" \
    --out "$OUT/seed${SEED}_chunk${CHUNK}.jsonl"
rc=$?
echo "rc=$rc end=$(date)"

# 统一重验证（永远在 rnad_eval 里）
conda deactivate 2>/dev/null
conda activate rnad_eval || exit 2
python -u -I harness/verify.py --in "$OUT/seed${SEED}_chunk${CHUNK}.jsonl" \
    --out "$OUT/seed${SEED}_chunk${CHUNK}.verified.jsonl" \
    --provenance "$OUT/seed${SEED}_chunk${CHUNK}.provenance.json"
exit $rc
