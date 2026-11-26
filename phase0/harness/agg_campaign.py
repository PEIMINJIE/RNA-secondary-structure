#!/usr/bin/env python3
"""Phase 0 campaign 汇总：每种子统计、cost-to-solve 分位、截尾(censoring)体检、墙钟核时。

注意：verify.py 只带过白名单字段，**不含** stop_reason / wall_sec / gen_solved。
所以这里把 verified（判据）与 raw（预算与截尾）按 (seed, id) 连接起来。

用法（计算节点上）：python -u -I harness/agg_campaign.py
"""
import glob, json, statistics as st

ROOT = '/path/to/RNA'
M = ['nemo', 'samfeo', 'rnainverse', 'desirna', 'samplingdesign']

ver, raw = {}, {}
for m in M:
    d = f'{ROOT}/results/solvedB/{m}_v2_B100000'
    vf = sorted(glob.glob(f'{d}/*.verified.jsonl'))
    rf = [f for f in sorted(glob.glob(f'{d}/seed*_chunk*.jsonl')) if '.verified.' not in f]
    ver[m] = [json.loads(l) for f in vf for l in open(f) if l.strip()]
    raw[m] = {(r['seed'], r['id']): r for f in rf for l in open(f) if l.strip()
              for r in [json.loads(l)]}

print('=== 条数 / 连接率 ===')
for m in M:
    miss = sum(1 for r in ver[m] if (r['seed'], r['id']) not in raw[m])
    print(f'{m}: verified {len(ver[m])}, raw {len(raw[m])}, 连不上 {miss}')

print('\n=== stop_reason 分布（raw）===')
for m in M:
    c = {}
    for r in raw[m].values():
        c[r.get('stop_reason')] = c.get(r.get('stop_reason'), 0) + 1
    print(m, c)

print('\n=== 截尾：未命中题里真正"撞到闸"的比例 ===')
for m in M:
    nm = [r for r in ver[m] if not r.get('mfe_hit')]
    cens = 0
    for r in nm:
        rr = raw[m].get((r['seed'], r['id']), {})
        if rr.get('stop_reason') in ('fold_budget', 'time_limit'):
            cens += 1
    print(f'{m}: 未命中 {len(nm)} 条，其中撞闸 {cens} 条 ({100*cens/max(1,len(nm)):.0f}%)')

print('\n=== 每种子 MFE/uMFE + 均值±std + 并集 ===')
rows_out = []
for m in M:
    rows = ver[m]
    seeds = sorted({r['seed'] for r in rows})
    mf, um = [], []
    for s in seeds:
        sub = [r for r in rows if r['seed'] == s]
        mf.append(sum(bool(r.get('mfe_hit')) for r in sub))
        um.append(sum(bool(r.get('umfe_hit')) for r in sub))
    mfu = len({r['id'] for r in rows if r.get('mfe_hit')})
    umu = len({r['id'] for r in rows if r.get('umfe_hit')})
    und = sum(1 for r in rows if not r.get('umfe_determined'))
    print(f'{m}: MFE {mf} mean {st.mean(mf):.1f}+-{st.stdev(mf):.1f} union {mfu} | '
          f'uMFE {um} mean {st.mean(um):.1f}+-{st.stdev(um):.1f} union {umu} | uMFE未判定 {und}')
    rows_out.append((m, st.mean(mf), st.stdev(mf), mfu, st.mean(um), st.stdev(um), umu))

def q(v, p):
    if not v:
        return float('nan')
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]

print('\n=== cost-to-solve（命中题）与墙钟 ===')
for m in M:
    hitk = {(r['seed'], r['id']) for r in ver[m] if r.get('mfe_hit')}
    fc = [raw[m][k].get('fold_calls_used') for k in hitk if k in raw[m]
          and isinstance(raw[m][k].get('fold_calls_used'), (int, float))]
    wt = [raw[m][k].get('wall_sec') for k in hitk if k in raw[m]
          and isinstance(raw[m][k].get('wall_sec'), (int, float))]
    allwt = [r.get('wall_sec') for r in raw[m].values() if isinstance(r.get('wall_sec'), (int, float))]
    print(f'{m}: 命中 {len(hitk)} | folds 中位 {q(fc,.5):.0f} p90 {q(fc,.9):.0f} max {max(fc) if fc else 0:.0f}'
          f' | 命中墙钟中位 {q(wt,.5):.1f}s p90 {q(wt,.9):.1f}s'
          f' | 全部墙钟中位 {q(allwt,.5):.1f}s 合计 {sum(allwt)/3600:.1f} 核时')

print('\n=== 生成侧自报 solved 与我们重验证的差（协议体检）===')
for m in M:
    gs = sum(1 for r in raw[m].values() if r.get('gen_solved'))
    vh = sum(1 for r in ver[m] if r.get('mfe_hit'))
    dis = 0
    for r in ver[m]:
        rr = raw[m].get((r['seed'], r['id']), {})
        if bool(rr.get('gen_solved')) != bool(r.get('mfe_hit')):
            dis += 1
    print(f'{m}: 自报 solved {gs} vs 重验证 MFE 命中 {vh} | 逐条不一致 {dis}')

print('\n=== 五方法联合：V2 上没有任何方法在 B=1e5 下解出的题 ===')
allhit = {}
for m in M:
    allhit[m] = {r['id'] for r in ver[m] if r.get('mfe_hit')}
    allhit[m + '_umfe'] = {r['id'] for r in ver[m] if r.get('umfe_hit')}
ids = sorted({r['id'] for r in ver['nemo']})
un_mfe = [i for i in ids if not any(i in allhit[m] for m in M)]
un_umfe = [i for i in ids if not any(i in allhit[m + '_umfe'] for m in M)]
print('MFE 全军覆没:', un_mfe)
print('uMFE 全军覆没:', un_umfe)
nm = {r['id']: r.get('puzzle_name') for r in ver['nemo']}
print('题名(MFE):', [(i, nm.get(i)) for i in un_mfe])

print('\n=== 只有某一个方法解出的题（方法互补性）===')
for m in M:
    only = [i for i in allhit[m] if not any(i in allhit[o] for o in M if o != m)]
    print(f'{m} 独占: {sorted(only)}')
