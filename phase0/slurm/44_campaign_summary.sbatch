#!/bin/bash
#SBATCH --job-name=rna_camp_sum
#SBATCH --output=/path/to/RNA/logs/44_camp_sum_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --exclude=c0706a-s23

# campaign 汇总：把折叠调用轴的 solved@B 曲线算出来。
# NEMO 命中即停 -> fold_calls_used 就是 cost-to-solve。
# SAMFEO 不在命中时停 -> 用 samfeo_first_hit_folds（它进度日志里首次 mfe count>0 的那一步换算）。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
echo "host=$(hostname) start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_eval || exit 2

for M in nemo samfeo; do
  D=$ROOT/results/solvedB/${M}_v2_B100000
  [ -d "$D" ] || { echo "跳过 $M（没有产物）"; continue; }
  N=$(ls "$D"/*.verified.jsonl 2>/dev/null | wc -l)
  echo "################ $M：$N 个分块 ################"
  [ "$N" -eq 0 ] && continue
  cat "$D"/*.verified.jsonl > "$ROOT/results/solvedB/${M}_v2_all.verified.jsonl"
  python -u -I harness/summarize.py --in "$ROOT/results/solvedB/${M}_v2_all.verified.jsonl" \
      --out "$ROOT/results/solvedB/${M}_v2_summary.csv" --group method,variant,gen_engine
  echo "--- solved@B（预算 = 折叠调用数，命中即停的真实 cost-to-solve）---"
  python -u -I harness/solved_at_b.py --in "$ROOT/results/solvedB/${M}_v2_all.verified.jsonl" \
      --out "$ROOT/results/solvedB/${M}_v2_curve.csv" \
      --cost-key fold_calls_used --bmin 1 --grid 20 || true
  if [ "$M" = "samfeo" ]; then
    echo "--- SAMFEO 的首次命中成本（公平口径）---"
    python -u -I harness/solved_at_b.py --in "$ROOT/results/solvedB/${M}_v2_all.verified.jsonl" \
        --out "$ROOT/results/solvedB/${M}_v2_curve_firsthit.csv" \
        --cost-key samfeo_first_hit_folds --bmin 1 --grid 20 || true
  fi
  echo
done

echo "=== 两种判据下的命中数（统一重验证口径）==="
python -u -c "
import glob, json
for m in ('nemo','samfeo'):
    fs = sorted(glob.glob('$ROOT/results/solvedB/%s_v2_B100000/*.verified.jsonl' % m))
    if not fs: continue
    rows=[json.loads(l) for f in fs for l in open(f) if l.strip()]
    seeds=sorted({r.get('seed') for r in rows})
    print(f'{m}: {len(rows)} 条, seeds {seeds}')
    for s in seeds:
        sub=[r for r in rows if r.get('seed')==s]
        mfe=sum(bool(r.get('mfe_hit')) for r in sub)
        umfe=sum(bool(r.get('umfe_hit')) for r in sub)
        cens=sum(1 for r in sub if r.get('stop_reason') in ('fold_budget','time_limit'))
        print(f'  seed {s}: 题数 {len(sub)} | MFE {mfe} | uMFE {umfe} | 撞预算/墙钟 {cens}')
"
echo "end=$(date)"
