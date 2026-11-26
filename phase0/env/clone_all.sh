#!/usr/bin/env bash
# 克隆/下载所有 A 类 baseline 与依赖源码。只做网络 I/O，不编译。
# 每个下载物各自独占一个空目录（下载内容视为不可信数据）。
set -u
ROOT=/path/to/RNA
TP=$ROOT/third_party
VS=$ROOT/vendor_src
LOG=$ROOT/logs/clone_all.log
: > "$LOG"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

clone() { # name url
  local name=$1
  local url=$2
  local dst="$TP/$name"
  if [ -d "$dst/.git" ]; then log "SKIP $name (已存在)"; return; fi
  rm -rf "$dst"
  log "CLONE $name <- $url"
  if git clone --quiet "$url" "$dst" >>"$LOG" 2>&1; then
    log "OK    $name @ $(git -C "$dst" rev-parse --short HEAD)"
  else
    log "FAIL  $name"
  fi
}

clone nemo              https://github.com/eternagame/nemo.git
clone samfeo            https://github.com/shanry/SAMFEO.git
clone samplingdesign    https://github.com/weiyutang1010/SamplingDesign.git
clone rna_design_lm     https://github.com/KuNyaa/RNA-Design-LM.git
clone eterna100_bench   https://github.com/eternagame/eterna100-benchmarking.git
clone rna_undesign      https://github.com/shanry/rna-undesign.git

# ViennaRNA 2.1.9 源码树（NEMO 必须编译进其中）
mkdir -p "$VS"
if [ ! -f "$VS/ViennaRNA-2.1.9.tar.gz" ]; then
  log "GET   ViennaRNA-2.1.9 源码"
  curl -fsSL -o "$VS/ViennaRNA-2.1.9.tar.gz" \
    https://www.tbi.univie.ac.at/RNA/download/sourcecode/2_1_x/ViennaRNA-2.1.9.tar.gz \
    >>"$LOG" 2>&1 && log "OK    ViennaRNA-2.1.9.tar.gz ($(du -h "$VS/ViennaRNA-2.1.9.tar.gz" | cut -f1))" \
    || log "FAIL  ViennaRNA-2.1.9 源码"
fi

log "DONE"
