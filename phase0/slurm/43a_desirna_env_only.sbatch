#!/bin/bash
#SBATCH --job-name=rna_dsr_env
#SBATCH --output=/path/to/RNA/logs/43a_dsr_env_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --exclude=c0706a-s23

# 只建 DesiRNA 需要的 conda 环境（它的 requirements: numpy matplotlib pandas multiprocess viennarna）。
# 冒烟测试放在单独的作业里。
set -uo pipefail
export TMPDIR=/tmp
cd /path/to/RNA || exit 1
echo "host=$(hostname) start=$(date)"

module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

if conda env list | awk '{print $1}' | grep -qx rnad_desirna; then
  echo "rnad_desirna 已存在，跳过"
else
  conda create -y -n rnad_desirna -c conda-forge -c bioconda \
      python=3.11 viennarna=2.6.4 numpy pandas matplotlib || exit 1
  conda run -n rnad_desirna python -m pip install --no-input multiprocess
fi

conda activate rnad_desirna || exit 2
python -c "import RNA, numpy, pandas, multiprocess; print('ViennaRNA', RNA.__version__, 'numpy', numpy.__version__, '| 依赖齐备')"
echo "end=$(date)"
