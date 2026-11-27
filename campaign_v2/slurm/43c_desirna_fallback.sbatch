#!/bin/bash
#SBATCH --job-name=rna_dsr_fb
#SBATCH --output=/path/to/RNA/logs/43c_dsr_fb_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G
#SBATCH --time=00:40:00
#SBATCH --exclude=c0706a-s23

# 退路：单独建 rnad_desirna 的 conda transaction 卡死了（>1 小时，正常 1-3 分钟）。
# DesiRNA 比 rnad_eval 只多一个依赖 multiprocess，所以直接装进 rnad_eval，
# 用 ViennaRNA 2.8.0 做它的生成侧（协议允许生成侧各用各的版本；用 2.8.0 反而更干净）。
# 装完立刻冒烟：三道小题，Turner 2004、命中即停、60 秒预算。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
cd "$ROOT" || exit 1
echo "host=$(hostname) start=$(date)"

module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_eval || exit 2

python -c "import multiprocess" 2>/dev/null && echo "multiprocess 已在" || \
  python -m pip install --no-input multiprocess
python -c "import RNA, numpy, pandas, matplotlib, multiprocess; print('ViennaRNA', RNA.__version__, '| DesiRNA 依赖齐备')" || exit 2

OUT=$ROOT/results/desirna_smoke
mkdir -p "$OUT"
cd "$OUT" || exit 1
for PID in 1 23 35; do
  python3 -c "
import json
rows = [json.loads(l) for l in open('$ROOT/data/eterna100/eterna100_v2.jsonl')]
r = [x for x in rows if x['id'] == $PID][0]
nl = chr(10)
s = r['target_structure']
open('in_$PID.txt', 'w').write('>name' + nl + 'ete_$PID' + nl + '>seq_restr' + nl + 'N'*len(s) + nl + '>sec_struct' + nl + s + nl)
print('题 $PID  L =', r['length'], ' 配对率 =', round(r['target_structure'].count('(')*2/r['length'], 2))
"
  echo "=== 题 $PID：-p 2004 -sws on -t 60 -R 10 ==="
  python -u "$ROOT/third_party/desirna/DesiRNA.py" -f "in_$PID.txt" -p 2004 -sws on -t 60 -R 10
  echo "退出码 $?"
done
echo "=== 产物 ==="
ls -la "$OUT"
echo "end=$(date)"
