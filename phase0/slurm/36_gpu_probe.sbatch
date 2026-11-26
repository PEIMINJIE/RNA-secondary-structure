#!/bin/bash
#SBATCH --job-name=rna_gpuprobe
#SBATCH --output=/path/to/RNA/logs/36_gpuprobe_%j.out
#SBATCH --partition=hpg-b200
#SBATCH --qos=YOUR_QOS
#SBATCH --gpus=1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=5
#SBATCH --mem=32G
#SBATCH --time=00:15:00

# 唯一一个 GPU 作业：量两件 CPU 上量不出来的事
#   1) 我们的 86 M 模型（structRFM 初始化）在 L=400、各 batch 下的真实显存与单步耗时
#      —— eager vs SDPA 两种注意力都量，CPU 上 SDPA 走 math 回退看不出差别
#   2) RNA-Design-LM（357.9 M）推理在作者默认 batch 下的真实显存
# 预算：1 块 B200 × ≤15 分钟。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1

echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} start=$(date)"
module load cuda/12.8.1 2>/dev/null || true
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_lm || exit 2
export LD_LIBRARY_PATH=/apps/compilers/cuda/12.8.1/lib64:${LD_LIBRARY_PATH:-}
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

python -u -I - <<'PY'
import time, torch
from transformers import AutoConfig, AutoModel
print("torch", torch.__version__, "| cuda", torch.version.cuda, "| device", torch.cuda.get_device_name(0))
dev = "cuda"
P = "/path/to/RNA/models/structRFM"
cfg = AutoConfig.from_pretrained(P)
L = 400

def run(attn, B, steps=3):
    torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
    m = AutoModel.from_config(cfg, attn_implementation=attn).to(dev)
    n = sum(q.numel() for q in m.parameters())
    opt = torch.optim.AdamW(m.parameters(), lr=1e-4)
    x = torch.randint(0, cfg.vocab_size, (B, L), device=dev)
    ts = []
    for i in range(steps):
        torch.cuda.synchronize(); t0 = time.perf_counter()
        with torch.autocast("cuda", dtype=torch.bfloat16):
            out = m(x).last_hidden_state
            loss = out.float().pow(2).mean()
        loss.backward(); opt.step(); opt.zero_grad(set_to_none=True)
        torch.cuda.synchronize(); ts.append(time.perf_counter() - t0)
    peak = torch.cuda.max_memory_allocated() / 2**30
    del m, opt, x
    return n, min(ts[1:] or ts), peak

print("\n### 我们的模型（86 M，structRFM 初始化），L=400，bf16 autocast + AdamW")
print(f"{'attn':8s}{'B':>6s}{'单步(ms)':>11s}{'峰值显存(GiB)':>15s}{'token/s':>12s}")
for attn in ("sdpa", "eager"):
    for B in (32, 64, 128, 256):
        try:
            n, dt, peak = run(attn, B)
            print(f"{attn:8s}{B:6d}{dt*1e3:11.1f}{peak:15.2f}{B*L/dt:12.0f}")
        except torch.cuda.OutOfMemoryError:
            print(f"{attn:8s}{B:6d}{'OOM':>11s}{'-':>15s}{'-':>12s}")
            torch.cuda.empty_cache()
        except Exception as e:
            print(f"{attn:8s}{B:6d}  失败: {type(e).__name__}: {str(e)[:60]}")
            torch.cuda.empty_cache()

print("\n### baseline 推理（357.9 M），贪心生成 L=400，看真实显存")
import sys
sys.path.insert(0, "/path/to/RNA/harness")
from load_lm import load_aliased_lm
torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
mdl, tok = load_aliased_lm("models/rna_design_lm/model/SL+RL", "RNA_DESIGN_LM", dtype=torch.bfloat16)
mdl = mdl.to(dev).eval()
print(f"权重加载后显存 {torch.cuda.memory_allocated()/2**30:.2f} GiB")
for B in (256, 1024):
    torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
    ids = torch.full((B, 8), 2, dtype=torch.long, device=dev)
    t0 = time.perf_counter()
    with torch.no_grad():
        out = mdl.generate(ids, max_new_tokens=128, do_sample=True, temperature=2.0,
                           pad_token_id=3)
    torch.cuda.synchronize(); dt = time.perf_counter() - t0
    peak = torch.cuda.max_memory_allocated() / 2**30
    print(f"  batch {B:5d}: 128 token {dt:6.2f}s | 峰值 {peak:5.2f} GiB | "
          f"{B*128/dt:8.0f} token/s | 推 512 token 外推 {peak*4:.1f} GiB")
    del ids, out
PY
echo "end=$(date)"
