#!/bin/bash
#SBATCH --job-name=rna_nemo_b
#SBATCH --output=/path/to/RNA/logs/41_nemo_budget_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=2G
#SBATCH --time=00:30:00
#SBATCH --exclude=c0706a-s23
# 重编带预算闸的 NEMO，并验证闸真的生效、计数真的落盘。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
VRNA=$ROOT/build/ViennaRNA-2.1.9
cd "$ROOT" || exit 1
echo "host=$(hostname) start=$(date)"
module load gcc/9.3.0 2>/dev/null || true
[ -f "$VRNA/lib/libRNA.a" ] || { echo "FATAL: libRNA.a 不在"; exit 1; }
python3 -I env/patch_nemo.py third_party/nemo/nemo.cpp "$VRNA/nemo/nemo.cpp" || exit 1
cd "$VRNA/nemo" || exit 1
rm -f nemo.o nemo
gcc -g -O2 -fopenmp -I../H -MD -MP -c -o nemo.o nemo.cpp || { echo "编译失败"; exit 1; }
gcc -g -O2 -fopenmp -L../lib -o nemo nemo.o -lstdc++ -lRNA -lm -ldl || { echo "链接失败"; exit 1; }
ls -la nemo
export NEMO_COUNT_FILE=$ROOT/logs/nemo_budget_smoke.jsonl
: > "$NEMO_COUNT_FILE"
TGT_L200=$(python3 -c "
import json
rows=[json.loads(l) for l in open('$ROOT/data/eterna100/eterna100_v2.jsonl')]
r=[x for x in rows if x['id']==69][0]; print(r['target_structure'])
")
echo "--- 闸 1：折叠预算 500（L=200 的题，一迭代约 673 次 fold，应在第 1-2 迭代后停）---"
OMP_NUM_THREADS=1 NEMO_FOLD_LIMIT=500 ./nemo -i 100000 "$TGT_L200" | tail -3
echo "--- 闸 2：墙钟 20 秒 ---"
OMP_NUM_THREADS=1 NEMO_TIME_LIMIT=20 ./nemo -i 100000 "$TGT_L200" | tail -3
echo "--- 闸 3：短题应正常解出并自然退出（stop=0）---"
OMP_NUM_THREADS=1 NEMO_FOLD_LIMIT=100000 ./nemo -i 100000 "(((((......)))))" | tail -3
echo "--- 落盘 ---"; cat "$NEMO_COUNT_FILE"
echo end=$(date)
