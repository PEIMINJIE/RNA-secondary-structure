#!/usr/bin/env python3
"""campaign 的第二条轴：墙钟秒数预算下的 solved@B（与 Koodli 文献曲线同轴，可直接比）。

命中即停的方法（NEMO/DesiRNA/RNAinverse），wall_sec 就是 cost-to-solve；
不在命中时停的方法（SAMFEO/SamplingDesign）其 wall_sec 是跑满闸的时间，
对它们这条曲线是**保守下界**（真实首次命中更早），已在输出里标注。

产物：results/solvedB/campaign_wall_curve.csv, campaign_fold_curve.csv
"""
import glob, json, csv, statistics as st

ROOT = '/path/to/RNA'
M = ['nemo', 'samfeo', 'rnainverse', 'desirna', 'samplingdesign']
STOP_AT_HIT = {'nemo': True, 'desirna': True, 'rnainverse': True,
               'samfeo': False, 'samplingdesign': False}
WGRID = [1, 3, 10, 30, 100, 300, 900]
FGRID = [1e2, 1e3, 1e4, 1e5, 1e6]

ver, raw = {}, {}
for m in M:
    d = f'{ROOT}/results/solvedB/{m}_v2_B100000'
    vf = sorted(glob.glob(f'{d}/*.verified.jsonl'))
    rf = [f for f in sorted(glob.glob(f'{d}/seed*_chunk*.jsonl')) if '.verified.' not in f]
    ver[m] = [json.loads(l) for f in vf for l in open(f) if l.strip()]
    raw[m] = {(r['seed'], r['id']): r for f in rf for l in open(f) if l.strip()
              for r in [json.loads(l)]}

def curve(m, key, grid, crit='mfe_hit'):
    seeds = sorted({r['seed'] for r in ver[m]})
    out = []
    for B in grid:
        per = []
        for s in seeds:
            n = 0
            for r in ver[m]:
                if r['seed'] != s or not r.get(crit):
                    continue
                c = raw[m].get((s, r['id']), {}).get(key)
                if isinstance(c, (int, float)) and c <= B:
                    n += 1
            per.append(n)
        out.append((B, st.mean(per), st.stdev(per) if len(per) > 1 else 0.0))
    return out

for key, grid, fn, label in (('wall_sec', WGRID, 'campaign_wall_curve.csv', '墙钟秒/题'),
                             ('fold_calls_used', FGRID, 'campaign_fold_curve.csv', '折叠调用/题')):
    print(f'\n=== solved@B，预算 = {label}（MFE 判据，5 seeds 均值±std）===')
    hdr = ['method', 'stop_at_hit'] + [f'B={g:g}' for g in grid]
    print(' | '.join(f'{h:>12}' for h in hdr))
    rows = [hdr]
    for m in M:
        c = curve(m, key, grid)
        cells = [f'{v:.1f}±{sd:.1f}' for _, v, sd in c]
        print(' | '.join([f'{m:>12}', f'{str(STOP_AT_HIT[m]):>12}'] + [f'{x:>12}' for x in cells]))
        rows.append([m, STOP_AT_HIT[m]] + [f'{v:.2f}' for _, v, _ in c])
    with open(f'{ROOT}/results/solvedB/{fn}', 'w', newline='') as f:
        csv.writer(f).writerows(rows)
    print('->', f'{ROOT}/results/solvedB/{fn}')

print('\n=== 同上，uMFE 判据 ===')
for key, grid, label in (('wall_sec', WGRID, '墙钟秒/题'), ('fold_calls_used', FGRID, '折叠调用/题')):
    print(f'-- {label}')
    for m in M:
        c = curve(m, key, grid, crit='umfe_hit')
        print(f'{m:>14}: ' + '  '.join(f'{v:.1f}' for _, v, _ in c))

print('\n=== 逐题 cost-to-solve（折叠调用，seed 中位；"-"=该方法 5 seed 全未命中）===')
ids = sorted({r['id'] for r in ver['nemo']})
name = {r['id']: r.get('puzzle_name') for r in ver['nemo']}
ln = {r['id']: r.get('length') for r in ver['nemo']}
out = [['id', 'puzzle', 'length'] + M]
for i in ids:
    row = [i, name.get(i), ln.get(i)]
    for m in M:
        cs = []
        for r in ver[m]:
            if r['id'] == i and r.get('mfe_hit'):
                c = raw[m].get((r['seed'], i), {}).get('fold_calls_used')
                if isinstance(c, (int, float)):
                    cs.append(c)
        row.append(f'{st.median(cs):.0f}' if cs else '-')
    out.append(row)
with open(f'{ROOT}/results/solvedB/per_puzzle_cost.csv', 'w', newline='') as f:
    csv.writer(f).writerows(out)
print('-> results/solvedB/per_puzzle_cost.csv  (', len(out) - 1, '题 )')
hard = [r for r in out[1:] if sum(1 for x in r[3:] if x == '-') >= 4]
print('五方法里至多 1 个解出的题:', [(r[0], r[1], r[2]) for r in hard])
