#!/bin/bash
#SBATCH --job-name=rna_c3
#SBATCH --output=/path/to/RNA/logs/51_c3_%A_%a.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=12:00:00
#SBATCH --exclude=c0706a-s23

# campaign_spec v2 的正式 campaign。资源（--cpus-per-task / --mem / --array）
# 由 slurm/launch_campaign_v3.sh 在提交时覆盖，不要直接 sbatch 这个文件。
#
# 入参（全部走 export + --export=ALL）：
#   METHOD  nemo|samfeo|desirna|samplingdesign|rnainverse
#   BENCH   v2|v1|taneda29|archiveii
#   N_CHUNKS  本 benchmark 切成几块
#   CHUNK     每块几题
#   FOLD_BUDGET（默认 100000）  FUSE_SEC（默认 7200）
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1

METHOD=${METHOD:?要 METHOD}
BENCH=${BENCH:?要 BENCH}
N_CHUNKS=${N_CHUNKS:?要 N_CHUNKS}
CHUNK=${CHUNK:?要 CHUNK}
FOLD_BUDGET=${FOLD_BUDGET:-100000}
FUSE_SEC=${FUSE_SEC:-7200}
# OUT_SUFFIX：重跑时换个输出目录，别覆盖已有结果（旧结果是预算实现度分析的证据）。
# STEPS_OVERRIDE：固定步数，绕开 steps_per_fold.json 的全局标定。
# DesiRNA 用它钉死 -s 110：该方法的折叠计数器测不到真实折叠量 —— 实测
# `折叠数 = 进程数 × 132.2`（折叠/进程标准差仅 2.2，r = +1.000），3,112 次干净运行里
# 78% 取值恰好 13,480，且这 78% 覆盖了全部 0–19 RE 步内命中的运行，也就是方法真正
# 工作的区间里一点分辨率都没有。所以 B→步数 的换算没有可信的标定值，与其让一个
# 测不出来的 folds_per_step 去决定步数，不如把步数本身当作声明的预算、如实写进报告。
# 110 比原来的 148 更小，成绩反而更高，所以这个选择不构成对 DesiRNA 的放水。
# 另外，改全局标定文件会让「已跑完」和「还在跑」的任务用不同步数，同一个格子内部
# 就不自洽了 —— 必须走这个 per-job 的开关。
OUT_SUFFIX=${OUT_SUFFIX:-}
STEPS_OVERRIDE=${STEPS_OVERRIDE:-0}

SEED=$(( SLURM_ARRAY_TASK_ID / N_CHUNKS ))
CI=$(( SLURM_ARRAY_TASK_ID % N_CHUNKS ))
OUT=$ROOT/results/campaignV2/${METHOD}_${BENCH}_B${FOLD_BUDGET}${OUT_SUFFIX}
mkdir -p "$OUT"
# STEM_SUFFIX：把一个 chunk 再切成并行的子块。用于「某个 chunk 单独超时」的补跑 ——
# chunk 内部是串行的，ids 81-100 这种长题块串下来 7.2 h，拆 4 份按成本均衡后只要 2.0 h。
# 必须同时给 IDS，并且把原来那个 chunk 的产物挪走，否则 (seed,id) 会重复。
# 产物名 seed{S}_chunk{C}{后缀}.jsonl 仍然匹配 table_v2.py 的 seed*_chunk*.jsonl。
STEM_SUFFIX=${STEM_SUFFIX:-}
STEM=$OUT/seed${SEED}_chunk${CI}${STEM_SUFFIX}

BENCH_FILE=$(python3 -c "
import json,sys
sys.path.insert(0,'$ROOT/harness')
from run_campaign_v2 import BENCHES
print('$ROOT/'+BENCHES['$BENCH'])")

# IDS 可由外部显式给（pilot 要跨长度分层，不能只取排序后的前 N 道）
if [ -n "${IDS:-}" ]; then
  echo "（用外部给定的题号）"
else
IDS=$(python3 -c "
import json
rows=[json.loads(l) for l in open('$BENCH_FILE') if l.strip()]
ids=sorted(r['id'] for r in rows)
print(','.join(str(i) for i in ids[$CI*$CHUNK:($CI+1)*$CHUNK]))")
fi

echo "host=$(hostname) method=$METHOD bench=$BENCH seed=$SEED chunk=$CI/$N_CHUNKS"
echo "cpus=$SLURM_CPUS_PER_TASK mem=${SLURM_MEM_PER_NODE:-?} B=$FOLD_BUDGET fuse=$FUSE_SEC"
echo "out=$OUT steps_override=$STEPS_OVERRIDE"
echo "题号: $IDS"

module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
case "$METHOD" in
  nemo|rnainverse|desirna) conda activate rnad_eval   || exit 2 ;;
  samfeo)                  conda activate rnad_samfeo || exit 2 ;;
  samplingdesign)          conda activate rnad_sd     || exit 2 ;;
  *) echo "未知 METHOD"; exit 3 ;;
esac

SO=()
[ "$STEPS_OVERRIDE" -gt 0 ] 2>/dev/null && SO=(--steps-override "$STEPS_OVERRIDE")
python -u -I harness/run_campaign_v2.py --method "$METHOD" --bench "$BENCH" \
    --seed "$SEED" --fold-budget "$FOLD_BUDGET" --fuse-sec "$FUSE_SEC" \
    "${SO[@]}" --ids "$IDS" --out "${STEM}.jsonl"
rc=$?
echo "run rc=$rc"

# 统一重验证永远在 rnad_eval 里（ViennaRNA 2.8.0）
conda deactivate 2>/dev/null
conda activate rnad_eval || exit 2
python -u -I harness/verify.py --in "${STEM}.jsonl" --out "${STEM}.verified.jsonl" \
    --provenance "${STEM}.provenance.json"
echo "rc=$rc end=$(date)"
exit $rc
