#!/usr/bin/env bash
# 创建本项目全部 conda 环境（幂等：已存在则跳过）。
# 环境划分见 baseline_plan.md §1：生成各用各的 ViennaRNA，验证统一 2.8.0。
set -uo pipefail

ROOT=/path/to/RNA
LOG=${LOG:-$ROOT/logs/create_envs.log}
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date +%F' '%T)] $*" | tee -a "$LOG"; }

module load conda >/dev/null 2>&1 || true
eval "$(conda shell.bash hook)" 2>/dev/null || { log "FATAL: conda hook 失败"; exit 1; }

has_env() { conda env list | awk '{print $1}' | grep -qx "$1"; }

create() { # name  "<pkg specs>"  ["<pip specs>"]
  local name=$1
  local specs=$2
  local pipspecs=${3:-}
  if has_env "$name"; then log "SKIP env $name（已存在）"; return 0; fi
  log "CREATE env $name : $specs"
  # shellcheck disable=SC2086
  if ! conda create -y -n "$name" -c conda-forge -c bioconda $specs >>"$LOG" 2>&1; then
    log "FAIL  conda create $name"; return 1
  fi
  if [ -n "$pipspecs" ]; then
    log "PIP   $name : $pipspecs"
    # shellcheck disable=SC2086
    conda run -n "$name" python -m pip install --no-input $pipspecs >>"$LOG" 2>&1 \
      || { log "FAIL  pip in $name"; return 1; }
  fi
  log "OK    env $name"
}

# 1) 统一验证环境（唯一有权产出论文数字的环境）
create rnad_eval "python=3.11 viennarna=2.8.0 numpy pandas scipy matplotlib pytest" \
                 "huggingface_hub"

# 2) SAMFEO 生成环境（其 requirements: numpy>=1.23 pandas>=1.4 ViennaRNA>=2.6）
create rnad_samfeo "python=3.11 viennarna=2.6.4 numpy pandas pytest"

# 3) SamplingDesign 生成环境（其 requirements 锁 py3.8.20 + viennarna 2.6.4 + numpy 1.24.4）
create rnad_sd "python=3.8 viennarna=2.6.4 numpy=1.24.4 matplotlib=3.7.5"

# 4) RNA-Design-LM 推理环境（GPU）。原仓库锁 torch==2.4.0（cu121），
#    但本集群的 GPU 是 B200（sm_100），cu121 轮子跑不起来 -> 用 cu128 的新 torch。
#    这是一处**必须在论文里交代的偏离**：只影响推理数值精度层面，不改模型权重。
create rnad_lm "python=3.11 viennarna=2.7.0 numpy pandas pyarrow fastparquet matplotlib" \
               "torch --index-url https://download.pytorch.org/whl/cu128"
if has_env rnad_lm; then
  conda run -n rnad_lm python -m pip install --no-input \
      "transformers==4.57.1" "tokenizers==0.22.1" "accelerate==1.11.0" \
      "safetensors>=0.6.2" "huggingface_hub>=0.36.0" "hf-xet" >>"$LOG" 2>&1 \
      && log "OK    rnad_lm 额外依赖" || log "WARN  rnad_lm 额外依赖安装有问题，见日志"
fi

log "ALL DONE"
conda env list | grep -E "^rnad" | tee -a "$LOG"
