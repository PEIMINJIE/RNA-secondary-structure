#!/bin/bash
#SBATCH --job-name=rna_nemo_build
#SBATCH --output=/path/to/RNA/logs/01_build_nemo_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --exclude=c0706a-s23

# 构建 ViennaRNA 2.1.9（NEMO 必须编译进其源码树）+ 打了计数器补丁的 NEMO。
set -uo pipefail
export TMPDIR=/tmp
ROOT=/path/to/RNA
BUILD=$ROOT/build
VRNA=$BUILD/ViennaRNA-2.1.9
cd "$ROOT" || exit 1
mkdir -p "$BUILD"

echo "host=$(hostname) job=${SLURM_JOB_ID:-NA} start=$(date)"
module load gcc/9.3.0 2>/dev/null || module load gcc/11.4.0 2>/dev/null || true
gcc --version | head -1

# 1) 解包（源码 tar 已在 vendor_src/，解到 build/ 里，保持 vendor_src 只读）
if [ ! -d "$VRNA" ]; then
  tar -xzf "$ROOT/vendor_src/ViennaRNA-2.1.9.tar.gz" -C "$BUILD" || exit 1
  echo "解包完成: $VRNA"
fi

# 2) configure + make（只要 libRNA 和头文件，绑定一律关掉）
cd "$VRNA" || exit 1
if [ ! -f lib/libRNA.a ]; then
  ./configure --prefix="$VRNA/_install" \
      --without-perl --without-python --without-python3 \
      --without-forester --without-kinfold --without-kinwalker \
      --without-doc --without-doc-pdf --without-doc-html \
      > "$ROOT/logs/vrna219_configure.log" 2>&1
  rc=$?
  echo "configure rc=$rc (log: logs/vrna219_configure.log)"
  [ $rc -ne 0 ] && { tail -30 "$ROOT/logs/vrna219_configure.log"; exit 1; }

  make -j"${SLURM_CPUS_PER_TASK:-4}" > "$ROOT/logs/vrna219_make.log" 2>&1
  rc=$?
  echo "make rc=$rc (log: logs/vrna219_make.log)"
  if [ ! -f lib/libRNA.a ]; then
    echo "FATAL: 没生成 lib/libRNA.a"; tail -40 "$ROOT/logs/vrna219_make.log"; exit 1
  fi
fi
echo "libRNA.a OK: $(ls -la lib/libRNA.a | awk '{print $5" bytes"}')"

# 3) 打补丁并编译 NEMO
mkdir -p "$VRNA/nemo"
cp -f "$ROOT/third_party/nemo/vrna185x.par" "$ROOT/third_party/nemo/list.e100" "$VRNA/nemo/"
python3 -I "$ROOT/env/patch_nemo.py" "$ROOT/third_party/nemo/nemo.cpp" "$VRNA/nemo/nemo.cpp" || exit 1

cd "$VRNA/nemo" || exit 1
gcc -g -O2 -fopenmp -I../H -MD -MP -c -o nemo.o nemo.cpp 2> "$ROOT/logs/nemo_compile.log"
rc=$?
echo "compile rc=$rc"
if [ $rc -ne 0 ]; then echo "--- 编译错误（前 40 行）---"; head -40 "$ROOT/logs/nemo_compile.log"; exit 1; fi
gcc -g -O2 -fopenmp -L../lib -o nemo nemo.o -lstdc++ -lRNA -lm -ldl 2>> "$ROOT/logs/nemo_compile.log"
rc=$?
echo "link rc=$rc"
if [ $rc -ne 0 ]; then echo "--- 链接错误 ---"; tail -20 "$ROOT/logs/nemo_compile.log"; exit 1; fi
ls -la nemo

# 4) 冒烟测试：小题 + 计数器 + 参数留痕（不传 -E => 内置 Turner 2004 + dangles=2）
export NEMO_COUNT_FILE=$ROOT/logs/nemo_smoke_counts.jsonl
: > "$NEMO_COUNT_FILE"
echo "--- smoke: Eterna100 #1 (L=16), 200 iter, Turner2004 ---"
timeout 600 ./nemo -v -i 200 "(((((......)))))"
echo "rc=$?"
echo "--- smoke: 同题 + -E（Turner1999 + dangles=1，仅作对照）---"
timeout 600 ./nemo -v -i 200 -E "(((((......)))))"
echo "rc=$?"
echo "--- 计数器落盘 ---"
cat "$NEMO_COUNT_FILE"

# 5) 给出稳定路径
ln -sfn "$VRNA/nemo/nemo" "$ROOT/build/nemo_bin"
echo "NEMO 可执行: $ROOT/build/nemo_bin -> $VRNA/nemo/nemo"
echo "end=$(date)"
