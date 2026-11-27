#!/usr/bin/env python3
"""把一个 benchmark 的题号按长度均衡切成 K 片，打印第 k 片的题号（逗号分隔）。

解码成本 ≈ 候选数 × 序列长度，所以按题数平均切是错的：V2 最长题 400 nt、
最短 12 nt，差 33 倍。这里用 LPT（最长优先塞进当前最空的一片）做均衡，
目标是各片的 sum(length) 尽量齐，这样 K 张卡几乎同时收工。
"""
from __future__ import annotations

import argparse
import heapq
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCHES = {
    "v2": "data/eterna100/eterna100_v2.jsonl",
    "v1": "data/eterna100/eterna100_v1.jsonl",
    "taneda29": "data/taneda/taneda29.jsonl",
    "taneda27": "data/taneda/taneda27.jsonl",
    "archiveii": "data/archiveii/archiveii1144.jsonl",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True, choices=sorted(BENCHES))
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--shard", type=int, help="要哪一片（0 起）；不给就打印全部片的统计")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(os.path.join(ROOT, BENCHES[args.bench]))
            if l.strip()]
    rows.sort(key=lambda r: -r["length"])

    heap = [(0, i, []) for i in range(args.shards)]
    heapq.heapify(heap)
    for r in rows:
        load, i, ids = heapq.heappop(heap)
        ids.append(r["id"])
        heapq.heappush(heap, (load + r["length"], i, ids))

    shards = {i: (load, sorted(ids)) for load, i, ids in heap}

    if args.shard is None:
        for i in sorted(shards):
            load, ids = shards[i]
            print(f"shard {i}: {len(ids):4d} 题, sum(L)={load:6d}")
        loads = [shards[i][0] for i in shards]
        print(f"不均衡度 max/min = {max(loads) / max(1, min(loads)):.3f}")
    else:
        print(",".join(str(x) for x in shards[args.shard][1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
