#!/usr/bin/env python3
"""截尾体检：撞墙钟闸的那些运行，到底有没有留下候选序列？

这决定了 solved@B 曲线对各方法是否公平：
若某方法超时就什么都不吐，而另一个方法超时会吐"当前最好"，
那么前者在同一预算下被系统性低估。

用法（计算节点上）：python -u -I harness/censoring_audit.py
"""
import glob, json

ROOT = '/path/to/RNA'
M = ['nemo', 'samfeo', 'rnainverse', 'desirna', 'samplingdesign']

print(f'{"method":16s} {"stop_reason":28s} {"n":>5s} {"无序列":>7s} {"有序列但未命中":>14s}')
for m in M:
    d = f'{ROOT}/results/solvedB/{m}_v2_B100000'
    rf = [f for f in sorted(glob.glob(f'{d}/seed*_chunk*.jsonl')) if '.verified.' not in f]
    raw = [json.loads(l) for f in rf for l in open(f) if l.strip()]
    vf = sorted(glob.glob(f'{d}/*.verified.jsonl'))
    ver = {(r['seed'], r['id']): r for f in vf for l in open(f) if l.strip()
           for r in [json.loads(l)]}
    for sr in sorted({r.get('stop_reason') for r in raw}, key=str):
        sub = [r for r in raw if r.get('stop_reason') == sr]
        empty = sum(1 for r in sub if not (r.get('designed_sequence') or '').strip())
        nohit = sum(1 for r in sub
                    if (r.get('designed_sequence') or '').strip()
                    and not ver.get((r['seed'], r['id']), {}).get('mfe_hit'))
        print(f'{m:16s} {str(sr):28s} {len(sub):5d} {empty:7d} {nohit:14d}')

print('\n=== 撞闸时是否保留"当前最好"（协议对称性）===')
for m in M:
    d = f'{ROOT}/results/solvedB/{m}_v2_B100000'
    rf = [f for f in sorted(glob.glob(f'{d}/seed*_chunk*.jsonl')) if '.verified.' not in f]
    raw = [json.loads(l) for f in rf for l in open(f) if l.strip()]
    cens = [r for r in raw if r.get('stop_reason') in ('fold_budget', 'time_limit')]
    with_seq = sum(1 for r in cens if (r.get('designed_sequence') or '').strip())
    print(f'{m:16s} 撞闸 {len(cens):4d} 条，其中带候选序列 {with_seq:4d} 条 '
          f'({100*with_seq/max(1,len(cens)):.0f}%)')

print('\n=== 预算泄漏：命中的运行里墙钟超过 900 s 的有多少 ===')
for m in M:
    d = f'{ROOT}/results/solvedB/{m}_v2_B100000'
    rf = [f for f in sorted(glob.glob(f'{d}/seed*_chunk*.jsonl')) if '.verified.' not in f]
    raw = {(r['seed'], r['id']): r for f in rf for l in open(f) if l.strip()
           for r in [json.loads(l)]}
    vf = sorted(glob.glob(f'{d}/*.verified.jsonl'))
    ver = [json.loads(l) for f in vf for l in open(f) if l.strip()]
    hits = [r for r in ver if r.get('mfe_hit')]
    over = [r for r in hits
            if (raw.get((r['seed'], r['id']), {}).get('wall_sec') or 0) > 900.0]
    mx = max([(raw.get((r['seed'], r['id']), {}).get('wall_sec') or 0) for r in ver] or [0])
    print(f'{m:16s} 命中 {len(hits):4d}，其中墙钟>900s 的 {len(over):4d} '
          f'({100*len(over)/max(1,len(hits)):.0f}%) | 全批最大墙钟 {mx:.1f}s')
