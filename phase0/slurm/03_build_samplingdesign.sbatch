#!/bin/bash
#SBATCH --job-name=rna_sd_build
#SBATCH --output=/path/to/RNA/logs/03_build_sd_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --exclude=c0706a-s23

# 编译 SamplingDesign 的 C++ 采样器（LinearPartition 系）并做最小冒烟测试。
# 注意：它的内层折叠是自己的 beam 版 partition function（默认 beamsize=250，近似），
# 不是 ViennaRNA 精确 DP —— 预算计数必须单独处理，见 DEPLOY.md「已知缺口」。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
SD=$ROOT/third_party/samplingdesign
cd "$SD" || exit 1

echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} start=$(date)"
module load gcc/12.2.0 2>/dev/null || module load gcc/11.4.0 2>/dev/null || true
g++ --version | head -1

make 2>&1 | tail -20
ls -la bin/main || { echo "FATAL: bin/main 未生成"; exit 1; }

module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_sd || { echo "FATAL: rnad_sd 环境不存在（先跑 00_create_envs）"; exit 2; }
python -c "import RNA; print('生成侧 ViennaRNA', RNA.__version__)"

echo "--- 冒烟：Eterna100 #1 (L=16)，20 步 ---"
mkdir -p "$ROOT/results/sd_smoke"
echo "(((((......)))))" | timeout 900 python main --step 20 --num_thread 4 \
    > "$ROOT/results/sd_smoke/puzzle1.txt" 2>&1
echo "rc=$?"
tail -20 "$ROOT/results/sd_smoke/puzzle1.txt"
echo "end=$(date)"
