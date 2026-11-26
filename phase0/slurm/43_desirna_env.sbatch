#!/bin/bash
#SBATCH --job-name=rna_dsr_env
#SBATCH --output=/path/to/RNA/logs/43_dsr_env_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:30:00
#SBATCH --exclude=c0706a-s23

# DesiRNA 环境 + 冒烟。它是 V2 上最强的方法（我们重验证 92、它自报 97），必须进 A 类。
# 它默认参数是 Turner 1999 -> 我们一律传 -p 2004；-sws on 命中即停，-t 控预算。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
echo "host=$(hostname) start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1

if conda env list | awk '{print $1}' | grep -qx rnad_desirna; then
  echo "rnad_desirna 已存在"
else
  conda create -y -n rnad_desirna -c conda-forge -c bioconda \
      python=3.11 viennarna=2.6.4 numpy pandas matplotlib || exit 1
  conda run -n rnad_desirna python -m pip install --no-input multiprocess
fi
conda activate rnad_desirna || exit 2
python -c "import RNA, numpy, pandas, multiprocess; print('ViennaRNA', RNA.__version__, '| 依赖齐备')" || exit 2

OUT=$ROOT/results/desirna_smoke
mkdir -p "$OUT"
cd "$OUT" || exit 1
for PID in 1 23 35; do
  TGT=$(python3 -c "
import json
rows=[json.loads(l) for l in open('$ROOT/data/eterna100/eterna100_v2.jsonl')]
r=[x for x in rows if x['id']==$PID][0]
print(r['target_structure'])
")
  printf '>ete_%s\n%s\n' "$PID" "$TGT" > "in_$PID.txt"
  echo "=== 题 $PID (L=${#TGT})：Turner 2004、命中即停、60 秒预算 ==="
  /usr/bin/time -v -o "time_$PID.txt" python -u "$ROOT/third_party/desirna/DesiRNA.py" \
      -f "in_$PID.txt" -p 2004 -sws on -t 60 -R 10
  echo "退出码 $?"
  grep -E "Maximum resident set size|Elapsed .wall" "time_$PID.txt"
done
echo "=== 产物 ==="
ls -la "$OUT"
echo "end=$(date)"
