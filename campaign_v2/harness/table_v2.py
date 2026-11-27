#!/usr/bin/env python3
"""生成 campaign_spec v2 §1 要的那张表。

每个准确率格子报两个数：MFE 判据 和 uMFE 判据，各自「跨 seed 的单次运行均值 ± 标准差」。
**不取并集**（spec §3）。折叠调用数按题取中位数，分 mfe / pf / subopt 三类。
「计数方式」列直接取每行自带的 counting 标签，不做人工判断。

verify.py 只透传白名单字段（不含 fold_counts / counting / censored），所以这里
必须把 verified 和 raw 按 (seed, id) join 回去 —— 和 Phase 0 的 agg_campaign.py 同一个坑。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# python -I（隔离模式，3.11 起含 -P）不会把脚本目录加进 sys.path，
# 而所有 sbatch 都是用 -I 跑的 → 同目录的 mfe_equiv 必须显式加路径。
sys.path.insert(0, os.path.join(ROOT, "harness"))
RES = os.path.join(ROOT, "results", "campaignV2")

BENCH_ORDER = ["v2", "v1", "taneda29", "taneda27", "archiveii"]
# spec §2 规定的 seed 数。表头按它写（pass@8 等），同时拿它校验实际跑到的 seed 数 ——
# 一个格子悄悄少了几个 seed，均值和标准差都会变，但看表的人看不出来。
BENCH_SEEDS = {"v2": 8, "v1": 8, "taneda29": 16, "taneda27": 16, "archiveii": 1}
# spec §2 定的名义预算（折叠调用数）；格子目录名里的 `_B10000` 就是它。
# 任何格子的实际预算与它不符，都必须在格子里自己报出来 —— 实测 LM 在
# v1 / taneda29 / archiveii 上只跑了 1,000，是基线的 1/10，而表原来看不出这件事。
NOMINAL_B = 10000
BENCH_LABEL = {"v2": "Eterna100-V2", "v1": "Eterna100-V1",
               "taneda29": "Rfam-Taneda(29)", "taneda27": "Rfam-Taneda(27)",
               "archiveii": "ArchiveII"}
METHOD_LABEL = {"nemo": "NEMO", "desirna": "DesiRNA", "rnainverse": "RNAinverse-pf",
                "samfeo": "SAMFEO", "samplingdesign": "SamplingDesign",
                "rna_design_lm_slrl": "RNA-Design-LM (SL+RL)",
                "rna_design_lm_sl": "RNA-Design-LM (SL)"}
COUNT_LABEL = {
    "exact_cpp_counter": "精确（C++ 计数器）",
    "exact_monkeypatch": "精确（monkeypatch）",
    # 原始数据里的 counting 标签是 run_campaign_v2.py 写死的「打算达到」的口径，
    # 事后实测它没达到（见 COUNTER_UNUSABLE）。表里必须按实测标，不能按意图标。
    "exact_monkeypatch_multiproc":
        "**不可用**（monkeypatch 只抓到每进程固定 ~132 次初始化折叠）<sup>†</sup>",
    "exact_bestofN_selection": "精确（best-of-N 选择）",
    "structural_steps_x_samplesize": "结构性（步数×样本数，C++ 未插桩）",
    # RNAinverse 的 fold_calls_used = max(Python 可见计数, 墙钟 ÷ 该长度单次 mfe 标定)，
    # 实际由后者主导（可见计数每次 inverse_* 只算 1）。所以它既不是精确计数、
    # 也不只是「下界」，而是**mfe 等效工作量**；分 mfe/pf/subopt 的分解对它不存在。
    "lower_bound_c_internal_invisible":
        "mfe 等效（墙钟÷单次mfe标定，与可见计数取 max；C 内部折叠不可见）",
}


# 计数器不可用的方法：它报的数不是「方法做了多少次折叠」，填进表里会被当成真数读。
# DesiRNA 的实测证据（3,112 次干净运行，即修掉工作目录竞态之后的 `_fix` 数据）：
#   · fold_budget_used = n_counting_processes × 132.2（折叠/进程标准差只有 2.2，r = +1.000）
#   · 3,112 行里 2,424 行（78%）取值**恰好** 13,480，且这 78% 覆盖了全部
#     「0–19 个 RE 步内命中」的运行 —— 也就是方法真正工作的那个区间里，
#     计数器一点分辨率都没有（16 nt 的 Simple Hairpin 7 秒解出，也报 13,480）
#   · 只在 ≥20 步才动：20–59 步中位 53,680、≥60 步中位 107,280，台阶 ≈ 13,400
#     ＝ 约 101 个进程 —— 变的是进程数，不是折叠数
#   · 与墙钟 r = +0.52，但这个相关完全由进程数中介（进程数 vs 墙钟同为 +0.518）
# 结论：monkeypatch 只抓到了每个进程固定的那段初始化折叠，真正的搜索折叠发生在
# 看不到的地方。所以 DesiRNA 的预算只能用**声明的 RE 步数** + 轨迹给出的首次命中步，
# 绝对折叠量一律走 mfe_equiv.py 的 CPU 时间轴。
COUNTER_UNUSABLE = {"desirna"}


def counts_cell(rows, kind):
    """分类型折叠数的单元格。全 0 但预算非 0 时要写「不可分解」而不是 0 ——
    RNAinverse 的折叠全在 C 内部，Python 层的 monkeypatch 一次也看不见，
    写 0 会被读成「它没做这类折叠」。"""
    ms = {r.get("method") for r in rows.values()} - {None}
    if ms & COUNTER_UNUSABLE:
        return "测不到<sup>†</sup>"
    v = med_counts(rows, kind)
    if v is None:
        return "—"
    if v == 0:
        tot = [r.get("fold_budget_used") or 0 for r in rows.values()]
        vis = sum((r.get("fold_counts") or {}).get(k, 0) or 0
                  for r in rows.values() for k in ("mfe", "pf", "subopt"))
        if vis == 0 and any(t > 0 for t in tot):
            return "不可分解"
    return f"{v:,.0f}"


BAD_LINES = {}          # 文件 -> 不可解析的行数


def read_jsonl(path):
    """容错读取：跳过不可解析的行并记数。

    不能直接 json.loads 整个文件：曾有 pilot 与 full 并发写同一个
    `seed0_chunk0.jsonl`，产生**半行 JSON**。崩在这里会让整张表出不来，
    而静默跳过又会把数据问题藏起来 —— 所以跳过 + 在表末尾如实报告。
    """
    rows, bad = [], 0
    try:
        fh = open(path)
    except OSError:
        return rows
    with fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                bad += 1
    if bad:
        BAD_LINES[os.path.relpath(path, ROOT)] = bad
    return rows


def pick_cells():
    """每个 (method, bench) 选一个目录；有 `_fix` 后缀的优先。

    重跑会写到 `<cell>_fix`，旧目录保留作证据。两个都读进来的话，同一个
    (seed, id) 会被后读到的那份覆盖 —— 必须显式只取修正版。
    """
    found = {}
    fixed_methods = set()
    for d in sorted(glob.glob(os.path.join(RES, "*_B*"))):
        if not os.path.isdir(d):
            continue
        name = os.path.basename(d)
        core = name.split("_B")[0]                 # method_bench
        if "_" not in core:
            continue
        method, bench = core.rsplit("_", 1)
        is_fix = name.endswith("_fix")
        if is_fix:
            fixed_methods.add(method)
        found.setdefault((method, bench), {})[is_fix] = d

    # 一个方法只要有任何一个 `_fix` 目录，就**只**用它的 `_fix` 目录：
    # 重跑意味着旧数据的协议已被判定有问题，把两套协议混进同一行比缺一格更糟。
    #   DesiRNA : 工作目录竞态（同 seed 的并发 chunk 共用 work_root，先完成的那个
    #             rmtree 把还在跑的那个的目录删了）。v2 原始跑 70/796、v1 64/778 行
    #             「stop_reason 正常但没有序列」，重跑后 0；原始丢序列的那批里
    #             74%(v2) / 84%(v1) 其实是解出来了的。点估计差 +4.5/+5.3 pp(v2)、
    #             +3.2/+3.6 pp(v1)，方向是**低估**对手，所以必须重跑。
    #             重跑同时把步数从 148 降到 110（更小的预算），成绩反而更高 ——
    #             所以这个修正没有在给 DesiRNA 放水。
    #   SAMFEO  : 两个独立的理由，原来只记了第一个。
    #             ① `--seed` 不存在，种子其实走 `--start`，原来 8 个 seed 跑的是同一次
    #                运行（输出逐字节相同），点估计是对的、误差棒是假的（±0.0）。
    #             ② 原始格子同样中了上面那个工作目录竞态，而且表现形式比 DesiRNA 隐蔽：
    #                archiveii 199 行、v1 63 行、v2 66 行 `rc=1`（上游崩了），
    #                但这些行**都还留着序列**，所以「空序列」检查一个也抓不到 ——
    #                它们看起来是跑满预算的正常运行，实际上崩在中途。
    #                对应的 `_fix` 格子 rc≠0 全为 0。
    #                （所以「Bug A 的损害只限于 DesiRNA」这个说法是错的。）
    #                损害比例也印证了竞态这个机制：竞态发生在**同一 seed 的并发 chunk**
    #                之间，所以单 seed 切最多 chunk 的 archiveii 最重（199/1144 = 17%），
    #                8 seed、每 seed chunk 更少的 v1/v2 轻一半（63/800、66/800 = 8%），
    #                而只有 1 个 chunk 的 taneda29 原始格子 rc≠0 = 0。
    out = {}
    for (method, bench), ds in found.items():
        if method in fixed_methods:
            if True in ds:
                out[(method, bench)] = ds[True]
            # 没有 _fix 的 bench 就留空，不回退到旧目录
        else:
            out[(method, bench)] = ds[False] if False in ds else ds[True]
    return out


LM_PREF = ("full", "curve", "pilot")   # 同一 (flavor, bench) 的优先级，从高到低


def lm_files():
    """每个 (flavor, bench) 只返回一个 verified 文件，按 LM_PREF 取优先级最高的。"""
    by_key = {}
    for p in sorted(glob.glob(os.path.join(RES, "lm", "*.verified.jsonl"))):
        base = os.path.basename(p)[: -len(".verified.jsonl")]
        parts = base.split("_")
        if len(parts) < 3:
            continue
        tag, rest = parts[0], tuple(parts[1:])      # tag_flavor_bench
        if tag not in LM_PREF:
            continue
        rank = LM_PREF.index(tag)
        if rest not in by_key or rank < by_key[rest][0]:
            by_key[rest] = (rank, p)
    return [p for _r, p in by_key.values()]


def load():
    """返回 {(method, bench): {(seed, id): merged_row}}"""
    data = defaultdict(dict)
    cells = pick_cells()
    for (_method, _bench), cd in sorted(cells.items()):
        for vf in sorted(glob.glob(os.path.join(cd, "*.verified.jsonl"))):
            rf = vf.replace(".verified.jsonl", ".jsonl")
            raw = {(r["seed"], r["id"]): r for r in read_jsonl(rf)
                   if "seed" in r and "id" in r}
            for v in read_jsonl(vf):
                if "seed" not in v or "id" not in v:
                    continue
                k = (v["seed"], v["id"])
                r = raw.get(k, {})
                m = v.get("method") or r.get("method")
                b = r.get("benchmark") or v.get("benchmark")
                if b and b.startswith("eterna100_"):
                    b = b.replace("eterna100_", "")
                if not m or not b:
                    continue
                data[(m, b)][k] = {**r, **v}
    # LM 的产物不在 *_B* 目录里，单独收。按 (flavor, bench) 只取一次跑的结果：
    # `full_` 是正式跑，`curve_` 是定 N 用的单 seed 跑，`pilot_` 是 4 题的通路验证。
    # 混在一起会把不同题数/不同 seed 数的跑当成同一批（曾得到 41.0 ± 53.7 这种废数）。
    for vf in sorted(lm_files()):
        rf = vf.replace(".verified.jsonl", ".jsonl")
        raw = {(r["seed"], r["id"]): r for r in read_jsonl(rf)
               if "seed" in r and "id" in r}
        for v in read_jsonl(vf):
            if "seed" not in v or "id" not in v:
                continue
            k = (v["seed"], v["id"])
            r = raw.get(k, {})
            m = v.get("method") or r.get("method")
            b = r.get("benchmark") or v.get("benchmark")
            if not m or not b:
                continue
            data[(m, b)][k] = {**r, **v}
    return data


def pass_at(rows, field):
    """跨 seed 的单次运行命中数：每个 seed 单独算一次，然后取均值±标准差。"""
    per_seed = defaultdict(int)
    seeds = set()
    for (s, _pid), r in rows.items():
        seeds.add(s)
        if r.get(field):
            per_seed[s] += 1
    vals = [per_seed[s] for s in sorted(seeds)]
    if not vals:
        return None
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, sd, len(vals), vals


def med_counts(rows, kind):
    xs = []
    for r in rows.values():
        fc = r.get("fold_counts") or {}
        v = fc.get(kind)
        if v is not None:
            xs.append(v)
    return statistics.median(xs) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "TABLE_v2.md"))
    args = ap.parse_args()

    data = load()
    if not data:
        print(f"[table] {RES} 下还没有 verified 数据")
        return 1

    methods, benches = [], []
    for (m, b) in data:
        if m not in methods:
            methods.append(m)
        if b not in benches:
            benches.append(b)
    methods.sort(key=lambda m: list(METHOD_LABEL).index(m) if m in METHOD_LABEL else 99)
    benches.sort(key=lambda b: BENCH_ORDER.index(b) if b in BENCH_ORDER else 99)

    L = []
    L.append("# campaign_spec v2 §1 的表")
    L.append("")
    L.append("每个准确率格子两行：**MFE 判据** / **uMFE 判据**，都是「跨 seed 的单次运行"
             "均值 ± 标准差」，**未取并集**。折叠调用数按题取中位数。")
    L.append("")
    hdr = ["方法"] + [f"{BENCH_LABEL.get(b, b)}<br>pass@{BENCH_SEEDS.get(b, 'n')}"
                      for b in benches] + \
          ["mfe<br>调用数", "pf<br>调用数", "subopt<br>调用数", "计数方式"]
    L.append("| " + " | ".join(hdr) + " |")
    L.append("|" + "---|" * len(hdr))

    for m in methods:
        cells = [METHOD_LABEL.get(m, m)]
        for b in benches:
            rows = data.get((m, b))
            if not rows:
                cells.append("—")
                continue
            a = pass_at(rows, "mfe_hit")
            u = pass_at(rows, "umfe_hit")
            if a is None:
                cells.append("—")
            else:
                want = BENCH_SEEDS.get(b)
                n_pz = len({pid for _s, pid in rows})
                # seed 数或题数不足就直接在格子里标出来。缺一个 seed 不会报错、
                # 不会少一行，只会让 ± 后面那个数静静地变小。
                warn = ""
                if want and a[2] != want:
                    warn += f"<br>⚠️ {a[2]}/{want} seed"
                if want and a[2] * n_pz != len(rows):
                    warn += f"<br>⚠️ {len(rows)}/{a[2] * n_pz} 次运行"
                # 预算也必须在格子里自报。少一个数量级的预算不会让任何检查失败，
                # 只会让这一格看起来「成绩差」，而差的原因读表的人看不到。
                bud = sorted({r["budget"] for r in rows.values() if r.get("budget")})
                if bud and any(x != NOMINAL_B for x in bud):
                    s = "/".join(f"{int(x):,}" for x in bud)
                    warn += f"<br>🚨 B={s}<br>（名义 {NOMINAL_B:,}）"
                cells.append(f"{a[0]:.1f} ± {a[1]:.1f}<br>{u[0]:.1f} ± {u[1]:.1f}"
                             f"<br><sub>{a[2]} seeds × {n_pz} 题</sub>{warn}")
        allrows = {}
        label = set()
        for b in benches:
            for k, r in (data.get((m, b)) or {}).items():
                allrows[(b, ) + k] = r
                if r.get("counting"):
                    label.add(r["counting"])
        for kind in ("mfe", "pf", "subopt"):
            cells.append(counts_cell(allrows, kind))
        cells.append(" / ".join(sorted(COUNT_LABEL.get(x, x) for x in label)) or "—")
        L.append("| " + " | ".join(cells) + " |")

    # 预算不一致的脚注。放在表的正下方，因为它决定了整张表能不能横向读。
    off = []
    for m in methods:
        for b in benches:
            rows = data.get((m, b))
            if not rows:
                continue
            bud = sorted({r["budget"] for r in rows.values() if r.get("budget")})
            if bud and any(x != NOMINAL_B for x in bud):
                off.append((m, b, bud))
    if off:
        L.append("")
        L.append(f"🚨 **预算不一致：下列格子不是在名义预算 B = {NOMINAL_B:,} 次折叠调用上跑的**，"
                 "横向比较时必须把这件事一起说出去。")
        L.append("")
        L.append("| 方法 | benchmark | 实际 B | 相对名义 |")
        L.append("|---|---|---|---|")
        for m, b, bud in off:
            s = "/".join(f"{int(x):,}" for x in bud)
            ratio = "/".join(f"1/{NOMINAL_B // int(x)}" if int(x) and NOMINAL_B % int(x) == 0
                             else f"{int(x) / NOMINAL_B:.2f}×" for x in bud)
            L.append(f"| {METHOD_LABEL.get(m, m)} | {BENCH_LABEL.get(b, b)} | {s} | {ratio} |")
        L.append("")
        L.append("预算小于名义值**对该方法不利**，所以这不是在给它加分；"
                 "但不标出来，读表的人会把它当成同预算的成绩。"
                 "补预算值多少，见 `reports/lm_curve_table.md` 的「饱和行为」一节 —— "
                 "那里用并集轴给出了上界。")

    # † 脚注的数字从数据里现算，不写死 —— 否则重跑换了数据，脚注会变成假证据。
    du = [r for (m, _b), rs in data.items() if m in COUNTER_UNUSABLE
          for r in rs.values()
          if r.get("fold_budget_used") and r.get("n_counting_processes")]
    if du:
        per = [r["fold_budget_used"] / r["n_counting_processes"] for r in du]
        from collections import Counter as _C
        modal, mc = _C(r["fold_budget_used"] for r in du).most_common(1)[0]
        flat = [r for r in du if r["fold_budget_used"] == modal
                and r.get("re_step_at_hit") is not None]
        L.append("")
        L.append(f"<sup>†</sup> **DesiRNA 的折叠计数器测不到它的折叠量**，所以这些格子"
                 f"宁可留空也不填一个会被当成真数读的数。实测证据（{len(du):,} 次干净运行）：")
        L.append("")
        L.append(f"- `折叠数 = 进程数 × {statistics.median(per):.1f}`，"
                 f"折叠/进程的标准差只有 {statistics.pstdev(per):.1f}，相关系数 r = +1.000 ——"
                 f"变的是**进程数**，不是折叠数。")
        L.append(f"- {mc:,}/{len(du):,} 次运行（{mc / len(du):.0%}）的取值**恰好**是 {modal:,}。"
                 + (f"这批里命中步最大的是第 {max(r['re_step_at_hit'] for r in flat)} 个 RE 步 ——"
                    f"也就是说在 0 到那一步之间，计数器完全没有分辨率"
                    f"（16 nt 的 Simple Hairpin 7 秒解出，报的也是 {modal:,}）。"
                    if flat else ""))
        L.append("- 与墙钟的相关系数 +0.52 全部由进程数中介（进程数 vs 墙钟同为 +0.518）。")
        L.append("- 机制：monkeypatch 只抓到了每个进程固定的那段初始化折叠，"
                 "真正的搜索折叠发生在它看不到的地方。")
        L.append("")
        L.append("因此 DesiRNA 的预算只能这样说：**声明的 RE 步数 `-s 110`** "
                 "（加下面「步数轴」那张表给出的命中位置），绝对工作量看 "
                 "「第二条预算轴」里的 CPU 折算列。⚠️ 早期报出的"
                 "「折叠/步 ≈ 91.1」「超预算 14.75 倍」都是这个计数器的产物，已作废。")

    # 实现预算 vs 名义预算。spec §4 把折叠调用数定为预算主轴，那么「各方法是否真的
    # 在同一个 B 上」就是这张表能不能横向比的前提 —— 而步数驱动只保证期望对齐。
    # 实测：SAMFEO 0.98、SamplingDesign 1.00（折叠/步是常数），NEMO 从不超（解得早就停），
    # RNAinverse 10–13% 的运行超（C 内部折叠不可见，闸只能在两次调用之间检查）。
    # DesiRNA 这一行**没有数**：它的计数器测不到真实折叠（见 desirna_traj.py），
    # 所以「实现/名义预算」对它无定义，不要拿计数器的比值去填。
    L.append("")
    L.append("## 实现预算 / 名义预算（横向可比性的前提）")
    L.append("")
    L.append("| 方法 | benchmark | 中位 | p90 | 最大 | >1.1× 比例 | 可用严格截断修正 |")
    L.append("|---|---|---|---|---|---|---|")
    # 只有「命中即停」的方法，退出时的计数才等于命中时的计数，才能做严格截断 /
    # 导出 solved@B 曲线。判据是实测的实现/名义预算：NEMO 中位 0.04、RNAinverse 0.28
    # （都解得早就停），而 SAMFEO 恒为 0.98、SamplingDesign 恒为 1.00 —— 它们**跑满全程**
    # 才报结果，所以计数是总数。把 SAMFEO 当可截断会得到荒谬曲线
    # （B=100..5000 一直卡在 2.0、到 10000 才跳到 44.2），务必不要。
    TRUNCABLE = {"nemo", "rnainverse"}
    for m in methods:
        if m in COUNTER_UNUSABLE:
            # 比值的分子是个测不到真实折叠量的数（见 COUNTER_UNUSABLE 的注释），
            # 填进来会被读成「DesiRNA 超了 14.75 倍预算」—— 那是进程数的产物。
            L.append(f"| {METHOD_LABEL.get(m, m)} | （全部） | 测不到<sup>†</sup> | "
                     f"测不到<sup>†</sup> | 测不到<sup>†</sup> | 测不到<sup>†</sup> | "
                     f"折叠轴上不行；步数轴上可以（轨迹给出首次命中 RE 步）|")
            continue
        for b in benches:
            rows = data.get((m, b))
            if not rows:
                continue
            r = sorted((x.get("fold_budget_used") or 0) / x["budget"]
                       for x in rows.values() if x.get("budget"))
            if not r:
                continue
            n = len(r)
            ok = "是" if m in TRUNCABLE else "否（记的是总数，非命中时计数）"
            L.append(f"| {METHOD_LABEL.get(m, m)} | {BENCH_LABEL.get(b, b)} | "
                     f"{statistics.median(r):.2f} | {r[int(.9 * n)]:.2f} | {max(r):.2f} | "
                     f"{sum(1 for x in r if x > 1.1) / n:.0%} | {ok} |")

    # 第二条预算轴：mfe 等效工作量。必须有，因为三类方法的可计数性根本不同 ——
    # DesiRNA 的折叠计数器只反映进程数（见 COUNTER_UNUSABLE），RNAinverse 的折叠在
    # C 内部完全不可见。CPU 折算这条轴处处可用，
    # 用 SamplingDesign（比值 0.94）、SAMFEO（0.54）、NEMO（0.40）互校。
    L.append("")
    L.append("## 第二条预算轴：mfe 等效工作量")
    L.append("")
    L.append("| 方法 | benchmark | (a) 计数折算 | (b) CPU 折算 | b/a | 实现/名义 (按 b) |")
    L.append("|---|---|---|---|---|---|")
    try:
        import mfe_equiv
        have_eq = True
    except ImportError:
        have_eq = False
    if have_eq:
        for m in methods:
            for b in benches:
                rows = data.get((m, b))
                if not rows:
                    continue
                av, bv, ratio = [], [], []
                for r in rows.values():
                    if "length" not in r:
                        continue
                    # (a) 由计数折算：计数器不可用的方法一律不填，否则会出现一个
                    # 看着像真数、实际只反映进程数的「mfe 等效量」。
                    x = None if m in COUNTER_UNUSABLE else mfe_equiv.from_counts(r)
                    y = mfe_equiv.from_cpu(r)
                    if x:
                        av.append(x)
                    if y:
                        bv.append(y)
                    if x and y:
                        ratio.append(y / x)
                if not bv:
                    continue
                nom = statistics.median([r.get("budget") or 0 for r in rows.values()])
                med_b = statistics.median(bv)
                c_a = f"{statistics.median(av):,.0f}" if av else "测不到"
                c_r = f"{statistics.median(ratio):.2f}" if ratio else "—"
                c_n = f"{med_b / nom:.2f}×" if nom else "—"
                L.append(f"| {METHOD_LABEL.get(m, m)} | {BENCH_LABEL.get(b, b)} | "
                         f"{c_a} | {med_b:,.0f} | {c_r} | {c_n} |")
    else:
        L.append("| — | — | — | — | — | （harness/mfe_equiv.py 不可用）|")

    # 严格截断口径：命中必须发生在预算之内才算。只对能定出「命中时折叠数」的方法有效。
    L.append("")
    L.append("### 严格截断后的 MFE 命中（超预算才命中的一律作废）")
    L.append("")
    L.append("| 方法 | benchmark | 原始 | 严格截断 | 差 |")
    L.append("|---|---|---|---|---|")
    for m in methods:
        for b in benches:
            rows = data.get((m, b))
            if not rows:
                continue
            raw_hit = trunc_hit = 0
            usable = False
            for x in rows.values():
                if not x.get("mfe_hit"):
                    continue
                raw_hit += 1
                # DesiRNA 的 folds_at_hit = 命中步 × (fold_budget_used / 步数)，
                # 分子是那个只反映进程数的计数 —— 所以它在折叠轴上同样不可判。
                # DesiRNA 的截断只能在步数轴上做，见下面的「步数轴」小节。
                at = None if m in COUNTER_UNUSABLE else x.get("folds_at_hit")
                if at is None and m in TRUNCABLE:
                    at = x.get("fold_budget_used")
                if at is None:
                    continue
                usable = True
                if at <= (x.get("budget") or 0):
                    trunc_hit += 1
            if not usable:
                L.append(f"| {METHOD_LABEL.get(m, m)} | {BENCH_LABEL.get(b, b)} | "
                         f"{raw_hit} | 不可判 | — |")
            else:
                L.append(f"| {METHOD_LABEL.get(m, m)} | {BENCH_LABEL.get(b, b)} | "
                         f"{raw_hit} | {trunc_hit} | {trunc_hit - raw_hit:+d} |")

    # DesiRNA 唯一自洽的预算陈述：命中用掉了声明步数预算的百分之几。
    # 这个数不依赖任何折叠计数，只依赖轨迹文件里的 RE 步号和我们声明的 -s。
    desi = [(b, r) for (m, b), rs in data.items() if m == "desirna"
            for r in rs.values()
            if r.get("traj_hit") and r.get("re_step_at_hit") is not None
            and r.get("steps_requested")]
    if desi:
        L.append("")
        L.append("### 步数轴：DesiRNA 命中时用掉的步数预算比例")
        L.append("")
        L.append("折叠轴对 DesiRNA 不可用<sup>†</sup>，但轨迹文件给出命中发生在第几个 RE 步，"
                 "所以「命中用掉了多少预算」这句话仍然可以如实说。")
        L.append("")
        L.append("| benchmark | 命中数 | 命中步/步数预算 中位 | p90 | 最大 | 首步即命中 |")
        L.append("|---|---|---|---|---|---|")
        for b in benches:
            fr = sorted(r["re_step_at_hit"] / r["steps_requested"]
                        for bb, r in desi if bb == b)
            if not fr:
                continue
            n = len(fr)
            L.append(f"| {BENCH_LABEL.get(b, b)} | {n} | {statistics.median(fr):.3f} | "
                     f"{fr[int(.9 * n)]:.3f} | {max(fr):.3f} | "
                     f"{sum(1 for x in fr if x == 0) / n:.0%} |")

    # 保险丝触发率：spec §4 要求这个数是 0
    L.append("")
    L.append("## 墙钟保险丝触发率（spec §4 要求为 0）")
    L.append("")
    L.append("| 方法 | benchmark | 运行数 | 保险丝响 | 比例 |")
    L.append("|---|---|---|---|---|")
    for m in methods:
        for b in benches:
            rows = data.get((m, b))
            if not rows:
                continue
            n = len(rows)
            c = sum(1 for r in rows.values() if r.get("censored"))
            L.append(f"| {METHOD_LABEL.get(m, m)} | {BENCH_LABEL.get(b, b)} | {n} | "
                     f"{c} | {c / n:.1%} |")

    # 每题成本（spec 说 CPU-秒和 mfe-等效他们自己算，我们只报分类型折叠数与序列）
    L.append("")
    L.append("## 每次运行的墙钟中位数（仅供参考，不是主指标）")
    L.append("")
    L.append("| 方法 | benchmark | 核 | 墙钟中位 | 折叠中位 |")
    L.append("|---|---|---|---|---|")
    for m in methods:
        for b in benches:
            rows = data.get((m, b))
            if not rows:
                continue
            w = [r["wall_sec"] for r in rows.values() if r.get("wall_sec") is not None]
            f = [r["fold_budget_used"] for r in rows.values()
                 if r.get("fold_budget_used") is not None]
            cp = {r.get("cpus") for r in rows.values() if r.get("cpus")}
            c_f = ("测不到<sup>†</sup>" if m in COUNTER_UNUSABLE
                   else f"{statistics.median(f):,.0f}" if f else "—")
            c_w = f"{statistics.median(w):.1f} s" if w else "—"
            L.append(f"| {METHOD_LABEL.get(m, m)} | {BENCH_LABEL.get(b, b)} | "
                     f"{'/'.join(str(x) for x in sorted(cp)) or '?'} | {c_w} | {c_f} |")

    # 数据完整性如实报告：跳过坏行不等于没有问题
    L.append("")
    L.append("## 数据完整性")
    L.append("")
    if BAD_LINES:
        L.append("⚠️ 以下文件有不可解析的行（并发写入留下的半行 JSON），这些行已跳过：")
        L.append("")
        L.append("| 文件 | 坏行数 |")
        L.append("|---|---|")
        for p, n in sorted(BAD_LINES.items()):
            L.append(f"| `{p}` | {n} |")
    else:
        L.append("取用目录下的产物均可完整解析，无坏行。")
    L.append("")

    # 上游进程异常退出的行。单独查这一项的理由：一个方法可以先吐出几条序列再崩，
    # 那样行里有序列、stop_reason 也看着正常，实际上只跑了一小部分预算，却会被当成
    # 「跑满预算的一次运行」—— 在横向比较里这是最危险的一种污染，因为它让该方法
    # 看起来「用更少预算拿到同样成绩」。空序列检查抓不到它。
    # 实测：被 `_fix` 取代的那批原始格子里 samfeo_archiveii 199 行、v1 63 行、v2 66 行
    # 都是「崩了但仍有序列」（工作目录竞态），而对应的 `_fix` 格子是 0。
    crash_rows = []
    for (m, b), cd in sorted(pick_cells().items()):
        n = w = 0
        for p in sorted(glob.glob(os.path.join(cd, "*.jsonl"))):
            if ".verified." in p:
                continue
            with open(p) as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        r = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    if r.get("rc") not in (0, 7, None):   # 7/None 是我们自己的保险丝
                        n += 1
                        if (r.get("designed_sequence") or "").strip():
                            w += 1
        if n:
            crash_rows.append((m, b, n, w))
    if crash_rows:
        L.append("⚠️ 取用目录里有上游进程异常退出（`rc` 非 0）的行：")
        L.append("")
        L.append("| 方法 | benchmark | rc≠0 行数 | 其中仍有序列 |")
        L.append("|---|---|---|---|")
        for m, b, n, w in crash_rows:
            L.append(f"| {METHOD_LABEL.get(m, m)} | {BENCH_LABEL.get(b, b)} | {n} | {w} |")
        L.append("")
        L.append("「仍有序列」那一列是 0 才算安全：非 0 意味着该次运行崩在中途、"
                 "预算没跑满，但从行里看不出来。")
    else:
        L.append("取用目录里没有上游异常退出（`rc` 非 0）的行。")
    L.append("")
    L.append("取用的目录（有 `_fix` 的优先，旧目录保留作证据）：")
    L.append("")
    for (m, b), d in sorted(pick_cells().items()):
        L.append(f"- `{m}` / `{b}` → `{os.path.relpath(d, ROOT)}`")

    txt = "\n".join(L) + "\n"
    open(args.out, "w").write(txt)
    print(txt)
    print(f"-> {os.path.relpath(args.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
