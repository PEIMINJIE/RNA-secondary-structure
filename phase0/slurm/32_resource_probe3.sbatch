#!/bin/bash
#SBATCH --job-name=rna_resprobe3
#SBATCH --output=/path/to/RNA/logs/32_resprobe3_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --exclude=c0706a-s23

# probe1 的后半段（被 RNAinverse@L=400 卡死那部分）重做：
#   - RNAinverse 改用带单题超时的新 runner
#   - 权重加载（验证别名还原）+ 训练单步代理，用于 GPU 侧估算
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
OUT=$ROOT/results/resprobe3
mkdir -p "$OUT"
TV="/usr/bin/time -v"
peak() { command grep -E "Maximum resident set size|Elapsed \(wall clock\)" "$1" | sed 's/^\s*/    /'; }

echo "host=$(hostname) start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

echo "############ 1. RNAinverse-pf：短题 + 真实长题（单题 120 s 上限）############"
conda activate rnad_eval
$TV python -u -I harness/run_rnainverse.py --bench data/eterna100/eterna100_v2.jsonl \
    --out "$OUT/rnainverse.jsonl" --mode pf --budget 20000 --seed 0 \
    --ids 1,8,23,87,69 --puzzle-timeout 120 2> "$OUT/t_rnainv.txt"
peak "$OUT/t_rnainv.txt"

echo "############ 2. 权重加载（CPU）：别名还原能不能加载 ############"
conda deactivate; conda activate rnad_lm
$TV python -u -I harness/load_lm.py models/rna_design_lm/model/SL+RL RNA_DESIGN_LM 2> "$OUT/t_loadlm.txt"
peak "$OUT/t_loadlm.txt"

echo "############ 3. structRFM 加载 ############"
$TV python -u -I - <<'PY' 2> "$OUT/t_structrfm.txt"
from transformers import AutoConfig, AutoModel
from safetensors.torch import load_file
p = "/path/to/RNA/models/structRFM"
cfg = AutoConfig.from_pretrained(p)
m = AutoModel.from_config(cfg)
sd = load_file(p + "/model.safetensors")
n = sum(q.numel() for q in m.parameters())
print(f"structRFM: {type(m).__name__}, 参数 {n/1e6:.1f}M, 权重张量 {len(sd)}, hidden {cfg.hidden_size}, 层 {cfg.num_hidden_layers}, vocab {cfg.vocab_size}")
PY
peak "$OUT/t_structrfm.txt"

echo "############ 4. 训练单步的 CPU 代理（给 GPU 估算定标）############"
$TV python -u -I - <<'PY' 2> "$OUT/t_trainstep.txt"
import torch, time
from transformers import AutoConfig, AutoModel
torch.set_num_threads(4)
cfg = AutoConfig.from_pretrained("/path/to/RNA/models/structRFM")
m = AutoModel.from_config(cfg)
n = sum(q.numel() for q in m.parameters())
print(f"参数 {n/1e6:.1f}M -> fp32 权重 {n*4/2**20:.0f} MiB | 梯度 {n*4/2**20:.0f} MiB | AdamW 态 {n*8/2**20:.0f} MiB")
for B, L in ((16, 400), (32, 400), (64, 400)):
    x = torch.randint(0, cfg.vocab_size, (B, L))
    t0 = time.perf_counter()
    out = m(x).last_hidden_state
    out.float().pow(2).mean().backward()
    dt = time.perf_counter() - t0
    tok = B * L
    flops = 6 * n * tok
    print(f"  B={B:3d} L={L}: CPU 单步 {dt:.2f}s, {tok} token, 约 {flops/1e12:.2f} TFLOPs "
          f"-> B200 取 300 TFLOPS 有效算力则 {flops/300e12*1e3:.1f} ms/步")
    m.zero_grad(set_to_none=True)
PY
peak "$OUT/t_trainstep.txt"
echo "end=$(date)"
