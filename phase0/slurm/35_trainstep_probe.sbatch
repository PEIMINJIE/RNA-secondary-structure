#!/bin/bash
#SBATCH --job-name=rna_trainstep
#SBATCH --output=/path/to/RNA/logs/35_trainstep_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:40:00
#SBATCH --exclude=c0706a-s23

# probe3 的训练单步代理 OOM 了（32 G 不够，实测峰值 33.5 G）。
# 原因：eager attention 会把 B×H×L×L 的分数矩阵在 fp32 下**实体化**，L=400 时这项主导一切。
# 这里改用 SDPA（flash 路径，不实体化 L² 矩阵）并缩小 batch，顺带把两种实现的内存账算清楚。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
OUT=$ROOT/results/resprobe3; mkdir -p "$OUT"
TV="/usr/bin/time -v"
echo "host=$(hostname) start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_lm

$TV python -u -I - <<'PY' 2> "$OUT/t_trainstep_sdpa.txt"
import torch, time
from transformers import AutoConfig, AutoModel
torch.set_num_threads(4)
P = "/path/to/RNA/models/structRFM"
cfg = AutoConfig.from_pretrained(P)
n_layer, n_head, hid = cfg.num_hidden_layers, cfg.num_attention_heads, cfg.hidden_size
m = AutoModel.from_config(cfg, attn_implementation="sdpa")
n = sum(q.numel() for q in m.parameters())
print(f"模型 {n/1e6:.1f}M 参数 | {n_layer} 层 | {n_head} 头 | hidden {hid}")
print(f"优化器态（fp32 权重+梯度+AdamW 两个动量）= {n*16/2**30:.2f} GiB")
print()
print("【实测】CPU 单步（SDPA，fp32）与【推算】B200 换算：")
for B, L in ((8, 400), (16, 400), (32, 400)):
    x = torch.randint(0, cfg.vocab_size, (B, L))
    t0 = time.perf_counter()
    m(x).last_hidden_state.float().pow(2).mean().backward()
    dt = time.perf_counter() - t0
    tok = B * L
    fl = 6 * n * tok
    print(f"  B={B:3d} L={L}: CPU {dt:6.2f}s | {tok:6d} token | {fl/1e12:5.2f} TFLOPs "
          f"-> B200@300TFLOPS 约 {fl/300e12*1e3:6.1f} ms/步")
    m.zero_grad(set_to_none=True)
print()
print("【推算】激活显存：注意力实现决定一切（L=400）")
for B in (32, 64, 128, 256):
    eager = 2 * B * n_head * L * L * 2 * n_layer / 2**30   # bf16，两个 L² 张量/层
    flash = 4 * B * L * hid * 2 * n_layer / 2**30          # bf16，不实体化 L²
    print(f"  B={B:4d}: eager ≈ {eager:7.2f} GiB | SDPA/flash ≈ {flash:6.2f} GiB")
PY
command grep -E "Maximum resident|Elapsed" "$OUT/t_trainstep_sdpa.txt" | sed 's/^/  /'
echo "end=$(date)"
