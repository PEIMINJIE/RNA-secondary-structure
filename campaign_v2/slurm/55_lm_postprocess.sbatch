#!/bin/bash
#SBATCH --job-name=rna_lmpost
#SBATCH --output=/path/to/RNA/logs/55_lmpost_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=24G
#SBATCH --time=06:00:00
#SBATCH --exclude=c0706a-s23

# LM 解码之后的三步（纯 CPU）：
#   1. best-of-N 选择：每题的候选按顺序折，命中即停 → spec §4 的 B = N 口径
#   2. 统一重验证（ViennaRNA 2.8.0）
#   3. solved@N 曲线：把候选全折一遍记「首次命中下标」，任意 N ≤ N_REPEATS 免费导出
#
# 入参：BENCH N_REPEATS N_SEEDS TAG(默认 full) FLAVOR(默认 slrl)
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
BENCH=${BENCH:?要 BENCH}
N_REPEATS=${N_REPEATS:?要 N_REPEATS}
N_SEEDS=${N_SEEDS:-1}
TAG=${TAG:-full}
FLAVOR=${FLAVOR:-slrl}
OUT=$ROOT/results/campaignV2/lm
STEM=$OUT/${TAG}_${FLAVOR}_${BENCH}

echo "host=$(hostname) bench=$BENCH N=$N_REPEATS seeds=$N_SEEDS tag=$TAG"

SHARDS=( "${STEM}"_s*_decode.jsonl )
if [ ! -e "${SHARDS[0]}" ]; then
  echo "❌ 找不到分片解码产物 ${STEM}_s*_decode.jsonl"
  exit 1
fi
echo "分片 ${#SHARDS[@]} 个"

module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

# 合并前先查覆盖：每题的候选数必须等于 N_REPEATS × N_SEEDS，且题号集合完整。
# 分片解码曾因临时文件同名而互相覆盖，这一关必须留着。
conda activate rnad_eval >/dev/null 2>&1 || exit 2
python3 -I - "$BENCH" "$((N_REPEATS * N_SEEDS))" "${SHARDS[@]}" <<'PY'
import json, sys, os
from collections import Counter
sys.path.insert(0, os.path.join("harness"))
from run_campaign_v2 import BENCHES
bench, want_each, files = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
ids = {json.loads(l)["id"] for l in open(BENCHES[bench]) if l.strip()}
per = Counter()
for p in files:
    for ln in open(p):
        ln = ln.strip()
        if not ln:
            continue
        d = json.loads(ln)
        if (d.get("designed_sequence") or "").strip():
            per[d["id"]] += 1
missing = sorted(ids - set(per))
bad = {i: c for i, c in per.items() if c != want_each}
print(f"[coverage] 题 {len(per)}/{len(ids)}；每题应有 {want_each} 条")
if missing:
    print(f"[coverage] ❌ 缺题 {missing[:20]}{'...' if len(missing) > 20 else ''}")
    sys.exit(9)
if bad:
    ex = dict(list(bad.items())[:10])
    print(f"[coverage] ❌ 候选数不符的题 {len(bad)} 个，例 {ex}")
    sys.exit(9)
print("[coverage] ✅")
PY
[ $? -ne 0 ] && { echo "覆盖自检失败，不往下走"; exit 9; }

cat "${SHARDS[@]}" > "${STEM}_decode.jsonl"
echo "合并 -> ${STEM}_decode.jsonl ($(wc -l < "${STEM}_decode.jsonl") 行)"

echo "=== 1. best-of-N 选择（生成侧 ViennaRNA）==="
conda deactivate 2>/dev/null
conda activate rnad_lm || exit 2
python -u -I harness/lm_select.py --decode "${STEM}_decode.jsonl" --bench "$BENCH" \
    --n-repeats "$N_REPEATS" --n-seeds "$N_SEEDS" --flavor "$FLAVOR" \
    --out "${STEM}.jsonl" || exit $?

echo "=== 2. 统一重验证（ViennaRNA 2.8.0）==="
conda deactivate 2>/dev/null
conda activate rnad_eval || exit 2
python -u -I harness/verify.py --in "${STEM}.jsonl" --out "${STEM}.verified.jsonl" \
    --provenance "${STEM}.provenance.json" || exit $?

echo "=== 3. solved@N 曲线 ==="
python -u -I harness/lm_curve.py --bench "$BENCH" --procs "${SLURM_CPUS_PER_TASK:-16}" \
    --decode "${STEM}_decode.jsonl" --out "${STEM}_curve.json"

echo "end=$(date)"
