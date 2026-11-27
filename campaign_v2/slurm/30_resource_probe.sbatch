#!/bin/bash
#SBATCH --job-name=rna_resprobe
#SBATCH --output=/path/to/RNA/logs/30_resprobe_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --exclude=c0706a-s23

# 资源实测：把「要多少 CPU / 多少 mem / GPU 要几块」从猜变成量。
# 全部用 /usr/bin/time -v 读峰值 RSS。故意申请 64G，只为**量出**真实峰值，正式作业再按实测收紧。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
OUT=$ROOT/results/resprobe
mkdir -p "$OUT"
TV="/usr/bin/time -v"

echo "host=$(hostname) cpus=${SLURM_CPUS_PER_TASK:-?} start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

peak() { command grep -E "Maximum resident set size|Elapsed \(wall clock\)|Percent of CPU" "$1" | sed 's/^\s*/    /'; }

echo "############ 1. 统一验证器（3270 条，含 L=400）############"
conda activate rnad_eval
$TV python -u -I harness/verify.py --in data/koodli/designs.jsonl \
    --out "$OUT/verify_all.jsonl" 2> "$OUT/t_verify_all.txt"
peak "$OUT/t_verify_all.txt"

echo "############ 2. 单条最长序列（L=400）的 mfe+pf+subopt 峰值 ############"
$TV python -u -I - <<'PY' 2> "$OUT/t_single400.txt"
import json, os, sys
sys.path.insert(0, "/path/to/RNA/harness")
import RNA, rnaenv
rnaenv.pin_env()
rows = [json.loads(l) for l in open("/path/to/RNA/data/eterna100/eterna100_v2.jsonl")]
p = max(rows, key=lambda d: d["length"])
seq = p["sample_solution_vienna2"]
print("puzzle", p["id"], p["name"], "L =", p["length"])
fc = RNA.fold_compound(seq)
s, e = fc.mfe(); print("mfe", round(e, 2))
sols = fc.subopt(0); print("subopt(0) 结构数", len(sols))
fc2 = RNA.fold_compound(seq); print("pf", round(fc2.pf()[1], 2))
print("p(target)", fc2.pr_structure(p["target_structure"]))
PY
peak "$OUT/t_single400.txt"

echo "############ 3. NEMO 每迭代成本（L≈100 / 200 / 400，-i 1，单线程）############"
NEMO_DIR=$(dirname "$(readlink -f "$ROOT/build/nemo_bin")")
export NEMO_COUNT_FILE=$OUT/nemo_counts.jsonl
: > "$NEMO_COUNT_FILE"
python -I - > "$OUT/nemo_targets.txt" <<'PY'
import json
rows = [json.loads(l) for l in open("/path/to/RNA/data/eterna100/eterna100_v2.jsonl")]
for L in (100, 200, 400):
    p = min(rows, key=lambda d: abs(d["length"] - L))
    print(p["id"], p["length"], p["target_structure"])
PY
while read -r pid L tgt; do
  echo "--- NEMO puzzle $pid L=$L, 1 迭代, 1 线程 ---"
  (cd "$NEMO_DIR" && OMP_NUM_THREADS=1 $TV ./nemo -i 1 "$tgt") 2> "$OUT/t_nemo_$pid.txt" | tail -3
  peak "$OUT/t_nemo_$pid.txt"
done < "$OUT/nemo_targets.txt"
echo "--- NEMO 计数（每行一次运行）---"; cat "$NEMO_COUNT_FILE"

echo "############ 4. SAMFEO 每步成本（L=400，20 步）############"
conda deactivate; conda activate rnad_samfeo
TGT=$(awk 'NR==3{print $3}' "$OUT/nemo_targets.txt")
echo "$TGT" | $TV python -u -I harness/run_counted.py --counts "$OUT/samfeo_L400.counts.json" \
    --cwd "$OUT" --tag samfeo_L400 -- "$ROOT/third_party/samfeo/main.py" --online --step 20 \
    > "$OUT/samfeo_L400.raw.txt" 2> "$OUT/t_samfeo400.txt"
peak "$OUT/t_samfeo400.txt"
python -c "import json; d=json.load(open('$OUT/samfeo_L400.counts.json')); print('    counts:', d['counts']); print('    wall:', d['wall_sec'])"

echo "############ 5. RNAinverse-pf（L=400，预算 2000）############"
conda deactivate; conda activate rnad_eval
PID=$(awk 'NR==3{print $1}' "$OUT/nemo_targets.txt")
$TV python -u -I harness/run_rnainverse.py --bench data/eterna100/eterna100_v2.jsonl \
    --out "$OUT/rnainverse_L400.jsonl" --mode pf --budget 2000 --seed 0 --ids "$PID" \
    2> "$OUT/t_rnainv400.txt"
peak "$OUT/t_rnainv400.txt"

echo "############ 6. 权重加载（CPU）：别名还原是否真的能加载 ############"
conda deactivate; conda activate rnad_lm
$TV python -u -I harness/load_lm.py models/rna_design_lm/model/SL+RL RNA_DESIGN_LM 2> "$OUT/t_loadlm.txt"
peak "$OUT/t_loadlm.txt"
$TV python -u -I - <<'PY' 2> "$OUT/t_structrfm.txt"
import torch, json
from transformers import AutoConfig, AutoModel
p = "/path/to/RNA/models/structRFM"
cfg = AutoConfig.from_pretrained(p)
m = AutoModel.from_config(cfg)
sd = __import__("safetensors.torch", fromlist=["load_file"]).load_file(p + "/model.safetensors")
n = sum(q.numel() for q in m.parameters())
print(f"structRFM: {type(m).__name__}, 参数 {n/1e6:.1f}M, 权重张量 {len(sd)} 个, hidden {cfg.hidden_size}, 层 {cfg.num_hidden_layers}")
PY
peak "$OUT/t_structrfm.txt"

echo "############ 7. 训练侧单步显存的 CPU 代理估算 ############"
$TV python -u -I - <<'PY' 2> "$OUT/t_trainstep.txt"
import torch, time
from transformers import AutoConfig, AutoModel
p = "/path/to/RNA/models/structRFM"
cfg = AutoConfig.from_pretrained(p)
m = AutoModel.from_config(cfg)
n = sum(q.numel() for q in m.parameters())
print(f"参数 {n/1e6:.1f}M -> fp32 权重 {n*4/2**20:.0f} MiB；AdamW 态(2×fp32) {n*8/2**20:.0f} MiB；梯度 {n*4/2**20:.0f} MiB")
for B, L in ((32, 400), (64, 400), (128, 400)):
    x = torch.randint(0, cfg.vocab_size, (B, L))
    t0 = time.perf_counter()
    out = m(x).last_hidden_state
    loss = out.float().pow(2).mean(); loss.backward()
    dt = time.perf_counter() - t0
    act = B * L * cfg.hidden_size * cfg.num_hidden_layers * 4 / 2**20
    print(f"  B={B:3d} L={L}: CPU 单步 {dt:.2f}s；激活粗估 {act:.0f} MiB (fp32, 不含注意力中间量)")
    m.zero_grad(set_to_none=True)
PY
peak "$OUT/t_trainstep.txt"
echo "end=$(date)"
