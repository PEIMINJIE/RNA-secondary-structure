#!/bin/bash
#SBATCH --job-name=rna_lmpost2
#SBATCH --output=/path/to/RNA/logs/56_lmpost2_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --exclude=c0706a-s23

# 后处理的「接着跑」版本：解码分片已经合并、覆盖自检已经过，所以跳过那两步，
# 直接从 ${STEM}_decode.jsonl 开始做 select / verify / curve。
#
# 为什么需要它：55_lm_post_resume 的前身 55_lm_postprocess.sbatch 把 select 跑成单线程。
# 实测 V1 的 800,000 条候选要 2.66 h（13:38:15 -> 16:17:36），而 Eterna100-V2 是
# 8,000,000 条、平均 L³ 只差 1%，于是单线程要 26.8 h —— 12 h 限额装不下，
# 而且 select 是最后才落盘的，撞限额等于整段白跑（作业 52913344 就是这样，已主动撤掉）。
#
# 为什么先跑 V1 核对：并行化改的是「谁来折」，不该改「折出什么」。V1 的串行产出已经在手，
# 所以拿同一份解码文件再跑一遍并行版，sha256 必须完全相同，不同就停下不往 V2 走。
#
# 入参：
#   BENCH      v2|v1|taneda29|archiveii
#   N_REPEATS  每个 seed 的候选数（= B）
#   N_SEEDS    seed 数
#   TAG        产物前缀，默认 full
#   REPRO_BENCH / REPRO_N_REPEATS / REPRO_N_SEEDS  先做可复现核对的那个 benchmark（可空）
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1

BENCH=${BENCH:?要 BENCH}
N_REPEATS=${N_REPEATS:?要 N_REPEATS}
N_SEEDS=${N_SEEDS:?要 N_SEEDS}
TAG=${TAG:-full}
FLAVOR=${FLAVOR:-slrl}
LM=$ROOT/results/campaignV2/lm
PROCS=${SLURM_CPUS_PER_TASK:-16}

echo "host=$(hostname) bench=$BENCH N=$N_REPEATS seeds=$N_SEEDS procs=$PROCS"

module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

# ---------------------------------------------------------------- 可复现核对
if [ -n "${REPRO_BENCH:-}" ]; then
  echo "===================== 0. 并行实现可复现核对（$REPRO_BENCH） ====================="
  RB=$REPRO_BENCH
  RSTEM=$LM/${TAG}_${FLAVOR}_${RB}
  if [ ! -f "${RSTEM}.jsonl" ]; then
    echo "❌ 没有 ${RSTEM}.jsonl（串行产出），无法核对"; exit 7
  fi
  conda activate rnad_lm || exit 2
  python -u -I harness/lm_select.py --decode "${RSTEM}_decode.jsonl" --bench "$RB" \
      --n-repeats "${REPRO_N_REPEATS:?}" --n-seeds "${REPRO_N_SEEDS:?}" \
      --flavor "$FLAVOR" --procs "$PROCS" \
      --out "${RSTEM}.parallel_check.jsonl" \
      --repro-check "${RSTEM}.jsonl"
  rc=$?
  conda deactivate 2>/dev/null
  if [ $rc -ne 0 ]; then
    echo "❌ 可复现核对未过（rc=$rc），不往 $BENCH 走"; exit $rc
  fi
fi

# ---------------------------------------------------------------- 正式跑
STEM=$LM/${TAG}_${FLAVOR}_${BENCH}
if [ ! -f "${STEM}_decode.jsonl" ]; then
  echo "❌ 没有 ${STEM}_decode.jsonl"; exit 7
fi
NL=$(wc -l < "${STEM}_decode.jsonl")
WANT=$(python3 -I -c "
import json,sys
sys.path.insert(0,'$ROOT/harness')
from lm_select import BENCHES
n=sum(1 for l in open('$ROOT/'+BENCHES['$BENCH']) if l.strip())
print(n*$N_REPEATS*$N_SEEDS)")
echo "解码文件 $NL 行（应为 $WANT）"
# 逐题的覆盖自检在原作业 55_lmpost_*.out 里已经过了，这里只核总行数，别再扫一遍 800 万行。
[ "$NL" != "$WANT" ] && { echo "❌ 行数不符"; exit 9; }

echo
echo "===================== 1. best-of-N 选择（生成侧 ViennaRNA，${PROCS} 进程） ====================="
conda activate rnad_lm || exit 2
python -u -I harness/lm_select.py --decode "${STEM}_decode.jsonl" --bench "$BENCH" \
    --n-repeats "$N_REPEATS" --n-seeds "$N_SEEDS" --flavor "$FLAVOR" \
    --procs "$PROCS" --out "${STEM}.jsonl" || exit $?
conda deactivate 2>/dev/null

echo
echo "===================== 2. 统一重验证（ViennaRNA 2.8.0） ====================="
conda activate rnad_eval || exit 2
python -u -I harness/verify.py --in "${STEM}.jsonl" --out "${STEM}.verified.jsonl" \
    --provenance "${STEM}.provenance.json" || exit $?

echo
echo "===================== 3. solved@N 曲线 ====================="
python -u -I harness/lm_curve.py --bench "$BENCH" --procs "$PROCS" \
    --decode "${STEM}_decode.jsonl" --out "${STEM}_curve.json"

echo
echo "峰值内存：$(sacct -j "$SLURM_JOB_ID" --format=MaxRSS -n 2>/dev/null | tr -d ' ' | command grep -v '^$' | head -1)"
echo "end=$(date)"
