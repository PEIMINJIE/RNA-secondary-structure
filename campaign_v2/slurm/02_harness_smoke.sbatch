#!/bin/bash
#SBATCH --job-name=rna_harness
#SBATCH --output=/path/to/RNA/logs/02_harness_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=06:00:00
#SBATCH --exclude=c0706a-s23

# 统一验证 harness 的建立 + 自检：
#  A. 构建权威 Eterna100 V1/V2 文件 + 跨来源一致性审计
#  B. 自检：官方 sample solution 在我们的环境里必须判为 MFE 命中
#  C. 折叠调用成本标定（mfe / pf / subopt 的真实比值）
#  D. 把 Koodli 仓库 3270 条原始序列在**我们的** ViennaRNA 2.8.0 + Turner 2004 下重验证
#     -> 直接回答 baseline_plan.md §6 待核 #1–#3（NEMO 在 V2 到底多少）
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
mkdir -p data/koodli results logs

echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_eval || { echo "FATAL: rnad_eval 环境不存在（先跑 00_create_envs）"; exit 2; }
python -c "import RNA; print('ViennaRNA', RNA.__version__)" || exit 2

echo "=============== A. 构建 benchmark + 来源审计 ==============="
python -I harness/build_benchmarks.py || exit 1

echo "=============== B. 自检：官方 sample solution ==============="
python -I - <<'PY'
import json, os, subprocess, sys
ROOT = "/path/to/RNA"
sys.path.insert(0, os.path.join(ROOT, "harness"))
for ver in ("v1", "v2"):
    src = os.path.join(ROOT, "data/eterna100", f"eterna100_{ver}.jsonl")
    tmp = os.path.join(ROOT, "data/eterna100", f"_sample_{ver}.jsonl")
    with open(src) as fh, open(tmp, "w") as out:
        for ln in fh:
            d = json.loads(ln)
            out.write(json.dumps({"id": d["id"], "target_structure": d["target_structure"],
                                  "designed_sequence": d["sample_solution_vienna2"],
                                  "method": "official_sample_vienna2", "benchmark": f"eterna100_{ver}"}) + "\n")
    subprocess.run([sys.executable, "-I", os.path.join(ROOT, "harness/verify.py"),
                    "--in", tmp, "--out", os.path.join(ROOT, "results", f"selfcheck_sample_{ver}.jsonl"),
                    "--provenance", os.path.join(ROOT, "results", f"provenance_{ver}.json")], check=True)
PY
for v in v1 v2; do
  python -I - "$v" <<'PY'
import json, sys
v = sys.argv[1]
p = f"/path/to/RNA/results/selfcheck_sample_{v}.jsonl"
rows = [json.loads(l) for l in open(p) if l.strip()]
hit = [r for r in rows if r.get("mfe_hit")]
miss = [r for r in rows if not r.get("mfe_hit")]
print(f"[{v}] 官方 sample solution: MFE 命中 {len(hit)}/{len(rows)}, uMFE {sum(r.get('umfe_hit') for r in rows)}")
if miss:
    print(f"[{v}] 未命中的题号:", sorted(r['id'] for r in miss)[:40])
    print(f"[{v}] 注意：Eterna 的 sample solution 是在**游戏引擎**下给的，V1 表里 Vienna2 列才对应 Turner 2004。"
          " 未命中数 >0 需要逐题查，不能默认我们的 harness 错。")
PY
done

echo "=============== C. 折叠调用成本标定 ==============="
python -I harness/cost_calibrate.py --out harness/cost_model.json --reps 5 || exit 1

echo "=============== D. Koodli 原始序列重验证 ==============="
python -I harness/koodli_to_designs.py --out data/koodli/designs.jsonl || exit 1
wc -l data/koodli/designs.jsonl
python -I harness/verify.py --in data/koodli/designs.jsonl \
       --out results/koodli_verified.jsonl \
       --provenance results/koodli_provenance.json || exit 1
python -I harness/summarize.py --in results/koodli_verified.jsonl \
       --out results/koodli_summary.csv || exit 1

echo "=============== E. 计数器自检 ==============="
python -I - <<'PY'
import os, sys
ROOT = "/path/to/RNA"
sys.path.insert(0, os.path.join(ROOT, "harness"))
import RNA, rnaenv, foldcount
rnaenv.pin_env()
seq = "GGGGAAAACCCCAAAGGGGAAAACCCC"
legacy_fold = getattr(RNA, "fold", None)
expect_mfe = 2 if callable(legacy_fold) else 1
with foldcount.FoldCounter() as c:
    fc = RNA.fold_compound(seq)
    s, e = fc.mfe()
    fc.eval_structure(s)
    fc.subopt(0)
    fc2 = RNA.fold_compound(seq)
    fc2.pf()
    if callable(legacy_fold):
        legacy_fold(seq)
print("计数器结果:", c.counts, f"(expect mfe={expect_mfe})")
assert c.counts.get("mfe", 0) == expect_mfe, c.counts
assert c.counts.get("pf", 0) == 1, c.counts
assert c.counts.get("subopt", 0) == 1, c.counts
assert c.counts.get("eval", 0) == 1, c.counts
print("计数器自检通过 ✅")
PY
echo "end=$(date)"
