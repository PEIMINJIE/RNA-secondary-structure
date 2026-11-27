#!/bin/bash
#SBATCH --job-name=rna_cal2
#SBATCH --output=/path/to/RNA/logs/50_cal2_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=12G
#SBATCH --time=02:00:00
#SBATCH --exclude=c0706a-s23

# campaign_spec v2 的步数标定：测出每个方法「一步 ≈ 几次计入预算的折叠」。
# 同时验证两件 Phase 0 没查的事：
#   (a) SamplingDesign 的线程 flag 到底生效没有（Phase 0 传的是 --num_thread，
#       而它的 flag 叫 num_threads）
#   (b) DesiRNA 的 mp.Pool 子进程计数能不能被周期性落盘抓到
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
OUT=$ROOT/results/calibrate_v2
mkdir -p "$OUT"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

# 用 3 道短题标定（id 1/2/3 在 V2 里长度 16/?/?，便宜）
IDS=1,2,3

run() {   # run <method> <env> <steps>
  local m=$1 e=$2 s=$3
  echo; echo "################ $m （固定 $s 步）################"
  conda activate "$e" || { echo "激活 $e 失败"; return 2; }
  python -u -I harness/run_campaign_v2.py --method "$m" --bench v2 --seed 0 \
      --ids "$IDS" --steps-override "$s" --fuse-sec 900 \
      --out "$OUT/${m}_cal.jsonl"
  conda deactivate
}

run samfeo         rnad_samfeo 500
run desirna        rnad_eval   200
run samplingdesign rnad_sd     5

echo; echo "################ 汇总 ################"
conda activate rnad_eval || exit 2
python -u -I - <<'PY'
import json, glob, os, statistics
ROOT = "/path/to/RNA"
OUT = f"{ROOT}/results/calibrate_v2"
res = {}
for f in sorted(glob.glob(f"{OUT}/*_cal.jsonl")):
    rows = [json.loads(l) for l in open(f) if l.strip()]
    if not rows:
        continue
    m = rows[0]["method"]
    per = []
    for r in rows:
        # 只有实际跑满步数的行能用来定系数。提前解出就退出的行（steps_done 为空，
        # 或远小于 steps_requested）会把系数算成荒谬的小值。
        st, used = r.get("steps_done"), r.get("fold_budget_used")
        if r["method"] == "samplingdesign":
            st = r.get("steps_done")
        if st and used and st >= 0.5 * (r.get("steps_requested") or st):
            per.append(used / st)
        print(f"  {m} id={r['id']} L={r['length']} steps_req={r.get('steps_requested')} "
              f"steps_done={r.get('steps_done')} folds={used} "
              f"counts={r.get('fold_counts')} procs={r.get('n_counting_processes')} "
              f"stop={r.get('stop_reason')} wall={r.get('wall_sec')}")
        if m == "samplingdesign":
            print(f"    sd: sample_size={r.get('sd_sample_size')} "
                  f"threads_reported={r.get('sd_threads_reported')} "
                  f"cpus_given={r.get('sd_cpus_given')}")
    if per:
        res[m] = {"folds_per_step": round(statistics.median(per), 4),
                  "n_puzzles": len(per),
                  "per_puzzle": [round(x, 4) for x in per]}
        print(f"  -> {m}: 折叠/步 中位 {res[m]['folds_per_step']}")

p = f"{ROOT}/harness/steps_per_fold.json"
old = {}
if os.path.exists(p):
    old = json.load(open(p)).get("methods", {})
old.update(res)
# SamplingDesign 用结构性恒等式，不用标定中位数覆盖
if "samplingdesign" in old:
    old["samplingdesign"]["note"] = "结构性：每步求值 sample_size 个样本"
json.dump({"methods": old,
           "note": "折叠/步 = 计入预算的折叠（mfe+pf+subopt）除以实际步数"},
          open(p, "w"), indent=2, ensure_ascii=False)
print(f"\n-> {p}")
print(json.dumps(old, indent=2, ensure_ascii=False))
PY
echo "end=$(date)"
