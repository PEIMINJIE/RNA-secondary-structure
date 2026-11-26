#!/bin/bash
#SBATCH --job-name=rna_dsr_smoke
#SBATCH --output=/path/to/RNA/logs/43b_dsr_smoke_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --exclude=c0706a-s23

# DesiRNA 冒烟：三道小题，Turner 2004，命中即停，每题 60 秒预算。
# 所有输出直接打到作业日志，不做任何重定向。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
OUT=$ROOT/results/desirna_smoke
mkdir -p "$OUT"
cd "$OUT" || exit 1

echo "host=$(hostname) start=$(date)"
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_desirna || exit 2
python -c "import RNA; print('生成侧 ViennaRNA', RNA.__version__)"

for PID in 1 23 35; do
  python3 -c "
import json
rows = [json.loads(l) for l in open('$ROOT/data/eterna100/eterna100_v2.jsonl')]
r = [x for x in rows if x['id'] == $PID][0]
open('in_$PID.txt', 'w').write('>ete_$PID\n' + r['target_structure'] + '\n')
print('题 $PID  L =', r['length'])
"
  echo "=== 题 $PID：-p 2004 -sws on -t 60 -R 10 ==="
  python -u "$ROOT/third_party/desirna/DesiRNA.py" -f "in_$PID.txt" -p 2004 -sws on -t 60 -R 10
  echo "退出码 $?"
done

echo "=== 产物 ==="
ls -la "$OUT"
echo "end=$(date)"
