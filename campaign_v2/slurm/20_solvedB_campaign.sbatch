#!/bin/bash
#SBATCH --job-name=rna_solvedB
#SBATCH --output=/path/to/RNA/logs/20_solvedB_%A_%a.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=24:00:00
#SBATCH --array=0-4
#SBATCH --exclude=c0706a-s23

# ⚠️ 模板，**尚未提交**。提交前要定：METHOD、BENCH、BUDGET、seed 数、CPU 预算。
#
# 协议要点（比按预算档各跑一遍省一个数量级）：
#   搜索类方法命中即停 -> 一次跑到 B_max，记录「首次命中时用掉的折叠调用数」，
#   则任意 B ≤ B_max 的 solved@B 都可以从同一批运行里读出来（未命中 = 在 B_max 处右删失）。
#   所以 solved@B 曲线不需要对每个 B 重跑，只需要 per-puzzle 的 cost-to-solve。
#
# 用法：
#   sbatch --export=ALL,METHOD=rnainverse_pf,BENCH=v2,BUDGET=100000 slurm/20_solvedB_campaign.sbatch
#   （注意：VAR 要先 export 再 --export=ALL，不要把逗号列表塞进 --export，会被切断）

set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1

METHOD=${METHOD:-rnainverse_pf}
BENCH=${BENCH:-v2}
BUDGET=${BUDGET:-100000}
SEED=${SLURM_ARRAY_TASK_ID:-0}
OUT=$ROOT/results/solvedB/${METHOD}_${BENCH}
mkdir -p "$OUT"

echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} method=$METHOD bench=$BENCH budget=$BUDGET seed=$SEED start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

BENCH_FILE=$ROOT/data/eterna100/eterna100_${BENCH}.jsonl
[ -f "$BENCH_FILE" ] || { echo "FATAL: $BENCH_FILE 不存在（先跑 build_benchmarks.py）"; exit 2; }

case "$METHOD" in
  rnainverse_pf|rnainverse_mfe)
    conda activate rnad_eval || exit 2
    MODE=${METHOD#rnainverse_}
    python -I harness/run_rnainverse.py --bench "$BENCH_FILE" \
        --out "$OUT/seed${SEED}.jsonl" --mode "$MODE" --budget "$BUDGET" --seed "$SEED"
    ;;

  samfeo)
    conda activate rnad_samfeo || exit 2
    # SAMFEO 的 --step 是迭代数，不是折叠调用数；先用 run_counted 测出 step->调用 的换算，
    # 再把 step 设到对应 BUDGET。这里按经验值 step=BUDGET/10 起步，跑完以计数文件为准。
    STEP=$(( BUDGET / 10 ))
    while read -r line; do
      pid=$(python -c "import json,sys; d=json.loads(sys.argv[1]); print(d['id'])" "$line")
      tgt=$(python -c "import json,sys; d=json.loads(sys.argv[1]); print(d['target_structure'])" "$line")
      echo "$tgt" | timeout 86000 python -I harness/run_counted.py \
          --counts "$OUT/seed${SEED}_p${pid}.counts.json" \
          --cwd "$OUT" --tag "samfeo_${BENCH}_p${pid}_s${SEED}" \
          -- "$ROOT/third_party/samfeo/main.py" --online --step "$STEP" \
          > "$OUT/seed${SEED}_p${pid}.raw.txt" 2>&1
    done < "$BENCH_FILE"
    ;;

  nemo)
    # 不传 -E => 内置 Turner 2004 + dangles=2
    NEMO_DIR=$(dirname "$(readlink -f "$ROOT/build/nemo_bin")")
    export NEMO_COUNT_FILE=$OUT/seed${SEED}_counts.jsonl
    : > "$NEMO_COUNT_FILE"
    ITER=${ITER:-2500}
    while read -r line; do
      pid=$(python -c "import json,sys; d=json.loads(sys.argv[1]); print(d['id'])" "$line")
      tgt=$(python -c "import json,sys; d=json.loads(sys.argv[1]); print(d['target_structure'])" "$line")
      echo "## puzzle $pid"
      # OMP_NUM_THREADS 必须钉死：playout 的 RNG 非线程安全，线程数一变结果和调用数都变
      (cd "$NEMO_DIR" && OMP_NUM_THREADS=1 \
          timeout 86000 ./nemo -i "$ITER" "$tgt") > "$OUT/seed${SEED}_p${pid}.raw.txt" 2>&1
    done < "$BENCH_FILE"
    ;;

  *)
    echo "FATAL: 未知 METHOD=$METHOD（samplingdesign 与 rna_design_lm 需要各自的驱动，见 DEPLOY.md §8）"
    exit 3
    ;;
esac
rc=$?
echo "method=$METHOD seed=$SEED rc=$rc end=$(date)"

# 统一重验证（永远在 rnad_eval 里做）
conda deactivate 2>/dev/null
conda activate rnad_eval || exit 2
if [ -f "$OUT/seed${SEED}.jsonl" ]; then
  python -I harness/verify.py --in "$OUT/seed${SEED}.jsonl" \
      --out "$OUT/seed${SEED}.verified.jsonl" \
      --provenance "$OUT/seed${SEED}.provenance.json"
fi
exit $rc
