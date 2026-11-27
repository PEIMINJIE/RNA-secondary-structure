#!/bin/bash
#SBATCH --job-name=rna_nemo_rebuild
#SBATCH --output=/path/to/RNA/logs/01b_rebuild_nemo_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --exclude=c0706a-s23

# 只重打补丁 + 重编 NEMO（libRNA 已经建好了，不重跑 configure/make）。
# 修的是：计数器要 omp atomic（playout 在 OpenMP 并行段里，普通 ++ 会丢数）。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
VRNA=$ROOT/build/ViennaRNA-2.1.9
cd "$ROOT" || exit 1

echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} start=$(date)"
module load gcc/9.3.0 2>/dev/null || true
[ -f "$VRNA/lib/libRNA.a" ] || { echo "FATAL: libRNA.a 不存在，先跑 01_build_nemo"; exit 1; }

python3 -I "$ROOT/env/patch_nemo.py" "$ROOT/third_party/nemo/nemo.cpp" "$VRNA/nemo/nemo.cpp" || exit 1
cd "$VRNA/nemo" || exit 1
rm -f nemo.o nemo
gcc -g -O2 -fopenmp -I../H -MD -MP -c -o nemo.o nemo.cpp || { echo "编译失败"; exit 1; }
gcc -g -O2 -fopenmp -L../lib -o nemo nemo.o -lstdc++ -lRNA -lm -ldl || { echo "链接失败"; exit 1; }
ls -la nemo

export NEMO_COUNT_FILE=$ROOT/logs/nemo_smoke_counts_atomic.jsonl
: > "$NEMO_COUNT_FILE"
echo "--- 冒烟 1：#1 L=16，不传 -E（Turner 2004）---"
timeout 600 ./nemo -i 200 "(((((......)))))"; echo "rc=$?"
echo "--- 冒烟 2：#1 L=16，传 -E（Turner 1999 对照）---"
timeout 600 ./nemo -i 200 -E "(((((......)))))"; echo "rc=$?"
echo "--- 冒烟 3：#23 L=17，单线程（OMP_NUM_THREADS=1）看计数是否一致量级 ---"
OMP_NUM_THREADS=1 timeout 600 ./nemo -i 200 "((....)).((....))"; echo "rc=$?"
echo "--- 冒烟 4：同题 8 线程 ---"
OMP_NUM_THREADS=8 timeout 600 ./nemo -i 200 "((....)).((....))"; echo "rc=$?"
echo "--- 计数落盘 ---"; cat "$NEMO_COUNT_FILE"
echo "end=$(date)"
