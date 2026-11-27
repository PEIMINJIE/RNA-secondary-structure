#!/bin/bash
#SBATCH --job-name=rna_dsr_verify
#SBATCH --output=/path/to/RNA/logs/40_dsr_verify_%j.out
#SBATCH --partition=hpg-default
#SBATCH --qos=YOUR_BURST_QOS
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=2G
#SBATCH --time=01:00:00
#SBATCH --exclude=c0706a-s23
# DesiRNA 仓库自带的分档 benchmark 结果，在我们的 2.8.0 + Turner 2004 下重验证。
# 这直接回答两件事：(1) 它在 V2 上到底多少；(2) 「solved@B 没人报过」还成立吗。
set -uo pipefail
export TMPDIR=/tmp
cd /path/to/RNA || exit 1
module load conda >/dev/null 2>&1
eval "$(conda shell.bash hook)" || exit 1
conda activate rnad_eval || exit 2
python -u -I harness/desirna_published.py --out data/desirna/published.jsonl || exit 1
python -u -I harness/verify.py --in data/desirna/published.jsonl \
    --out results/desirna_published.verified.jsonl \
    --provenance results/desirna_published.provenance.json || exit 1
python -u -I harness/summarize.py --in results/desirna_published.verified.jsonl \
    --out results/desirna_published_summary.csv --group method,variant,gen_engine || exit 1
echo "=== 目标结构与权威表不一致的条数（若 >0 要查）==="
python -u -c "
import json
rows=[json.loads(l) for l in open('results/desirna_published.verified.jsonl')]
bad=[r for r in rows if r.get('target_matches_authoritative') is False]
print(f'不一致 {len(bad)} / {len(rows)}')
from collections import Counter
print('按档位:', Counter(r['variant'] for r in bad))
"
