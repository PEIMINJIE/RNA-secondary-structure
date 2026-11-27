#!/bin/bash
#SBATCH --job-name=rna_resprobe2
#SBATCH --output=/path/to/RNA/logs/31_resprobe2_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=03:00:00
#SBATCH --exclude=c0706a-s23

# 第一轮探测踩到一个坑：V2 里最长的题 #22 (L=400) 是**全不配对**的平凡题，
# 所以"L=400 的成本"量成了平凡情形。这里按**配对密度**挑真实的长题重测。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
OUT=$ROOT/results/resprobe2
mkdir -p "$OUT"
TV="/usr/bin/time -v"
peak() { command grep -E "Maximum resident set size|Elapsed \(wall clock\)" "$1" | sed 's/^\s*/    /'; }

echo "host=$(hostname) start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_eval

echo "############ 0. 选题：每个长度档里配对密度最高的 ############"
python -I - > "$OUT/targets.txt" <<'PY'
import json
rows = [json.loads(l) for l in open("/path/to/RNA/data/eterna100/eterna100_v2.jsonl")]
for r in rows:
    r["pair_frac"] = r["target_structure"].count("(") * 2 / r["length"]
for lo, hi in ((80, 130), (160, 240), (300, 400)):
    band = [r for r in rows if lo <= r["length"] <= hi and r["pair_frac"] >= 0.3]
    if not band:
        continue
    p = max(band, key=lambda r: (r["length"], r["pair_frac"]))
    print(p["id"], p["length"], round(p["pair_frac"], 3), p["target_structure"])
PY
command grep -oE "^[0-9]+ [0-9]+ [0-9.]+" "$OUT/targets.txt" | sed 's/^/    题号 长度 配对率: /'

echo "############ 1. 折叠成本（真实长题的 sample solution）############"
$TV python -u -I - <<'PY' 2> "$OUT/t_fold.txt"
import json, sys, time
sys.path.insert(0, "/path/to/RNA/harness")
import RNA, rnaenv
rnaenv.pin_env()
rows = {json.loads(l)["id"]: json.loads(l) for l in open("/path/to/RNA/data/eterna100/eterna100_v2.jsonl")}
ids = [int(l.split()[0]) for l in open("/path/to/RNA/results/resprobe2/targets.txt")]
for pid in ids:
    p = rows[pid]
    seq = p["sample_solution_vienna2"]
    L = p["length"]
    def t(f, n=3):
        ts = []
        for _ in range(n):
            t0 = time.perf_counter(); f(); ts.append(time.perf_counter() - t0)
        return min(ts)
    t_mfe_fresh = t(lambda: RNA.fold_compound(seq).mfe())
    fc = RNA.fold_compound(seq); fc.mfe()
    t_mfe_reuse = t(lambda: fc.mfe())
    t_pf = t(lambda: RNA.fold_compound(seq).pf())
    fc2 = RNA.fold_compound(seq); fc2.mfe()
    t_sub = t(lambda: fc2.subopt(0), 1)
    n_sub = len(fc2.subopt(0))
    print(f"题 {pid:3d} L={L:3d} 配对率 {p['target_structure'].count('(')*2/L:.2f}: "
          f"mfe(新建) {t_mfe_fresh*1e3:7.1f}ms  mfe(复用) {t_mfe_reuse*1e3:7.1f}ms  "
          f"pf {t_pf*1e3:7.1f}ms  subopt0 {t_sub*1e3:7.1f}ms (共最优 {n_sub} 个)")
PY
peak "$OUT/t_fold.txt"

echo "############ 2. NEMO 单迭代（真实长题，1 线程）############"
NEMO_DIR=$(dirname "$(readlink -f "$ROOT/build/nemo_bin")")
export NEMO_COUNT_FILE=$OUT/nemo_counts.jsonl
: > "$NEMO_COUNT_FILE"
while read -r pid L pf tgt; do
  echo "--- 题 $pid L=$L 配对率 $pf ---"
  (cd "$NEMO_DIR" && OMP_NUM_THREADS=1 $TV ./nemo -i 1 "$tgt") 2> "$OUT/t_nemo_$pid.txt" | command grep -E "^CNT|^STR" | cut -c1-120
  peak "$OUT/t_nemo_$pid.txt"
done < "$OUT/targets.txt"

echo "############ 3. SAMFEO 100 步（真实长题）############"
conda deactivate; conda activate rnad_samfeo
while read -r pid L pf tgt; do
  echo "--- 题 $pid L=$L ---"
  echo "$tgt" | timeout 3000 $TV python -u -I harness/run_counted.py \
      --counts "$OUT/samfeo_p${pid}.counts.json" --cwd "$OUT" --tag "samfeo_p$pid" \
      -- "$ROOT/third_party/samfeo/main.py" --online --step 100 \
      > "$OUT/samfeo_p${pid}.raw.txt" 2> "$OUT/t_samfeo_$pid.txt"
  peak "$OUT/t_samfeo_$pid.txt"
  python -c "
import json; d=json.load(open('$OUT/samfeo_p${pid}.counts.json'))
c=d['counts']; w=d['wall_sec']
print('    counts:', c)
print('    每步折叠:', {k: round(v/100,2) for k,v in c.items()}, '| 折叠耗时(s):', {k: round(v,2) for k,v in w.items()})
"
done < "$OUT/targets.txt"

echo "############ 4. SamplingDesign 20 步（真实长题，看内存与时间）############"
conda deactivate; conda activate rnad_sd
SD=$ROOT/third_party/samplingdesign
while read -r pid L pf tgt; do
  echo "--- 题 $pid L=$L ---"
  (cd "$SD" && echo "$tgt" | timeout 3000 $TV python main --step 20 --num_thread 4) \
      > "$OUT/sd_p${pid}.txt" 2> "$OUT/t_sd_$pid.txt"
  peak "$OUT/t_sd_$pid.txt"
  command grep -E "^(step|final|best)" "$OUT/sd_p${pid}.txt" | tail -2 | sed 's/^/    /'
done < "$OUT/targets.txt"
echo "end=$(date)"
