#!/bin/bash
#SBATCH --job-name=rna_env_sd
#SBATCH --output=/path/to/RNA/logs/00b_env_sd_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --exclude=c0706a-s23

# 补建 rnad_sd：conda-forge 没有 matplotlib=3.7.5（只有 matplotlib-base 的对应版本），
# 所以 conda 只装 python/viennarna/numpy，matplotlib 用 pip 按 SamplingDesign 的 pin 装。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} start=$(date)"

module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

if conda env list | awk '{print $1}' | grep -qx rnad_sd; then
  echo "rnad_sd 已存在，跳过创建"
else
  conda create -y -n rnad_sd -c conda-forge -c bioconda \
      python=3.8 viennarna=2.6.4 numpy=1.24.4 || { echo "FAIL conda create"; exit 1; }
  conda run -n rnad_sd python -m pip install --no-input "matplotlib==3.7.5" \
      || echo "WARN: matplotlib 装不上（只影响 SamplingDesign 的画图脚本，不影响生成序列）"
fi

conda activate rnad_sd || exit 2
python -c "import sys, RNA, numpy; print('py', sys.version.split()[0], '| ViennaRNA', RNA.__version__, '| numpy', numpy.__version__)"
python -c "import matplotlib; print('matplotlib', matplotlib.__version__)" || echo "matplotlib 缺失（可接受）"
echo "end=$(date)"
