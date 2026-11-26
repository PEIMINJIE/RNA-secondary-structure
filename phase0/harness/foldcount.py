"""折叠调用计数器（Python baseline 用）。

用法 A — 代码里显式包住：
    from foldcount import FoldCounter
    with FoldCounter() as fc:
        ...  # 任何调用 ViennaRNA 的代码
    fc.dump("counts.json")

用法 B — 不改 baseline 源码，靠 PYTHONSTARTUP 之外的注入：
    python -c "import foldcount; foldcount.install(dump_at_exit='counts.json')" 之后 runpy 目标脚本，
    或直接：python harness/run_counted.py --out counts.json -- <目标脚本> [args...]

计数口径（分类型，不折算）：
    mfe      : RNA.fold / fold_compound.mfe / mfe_window / subopt_zuker 的一次 O(L^3) 内外循环
    pf       : fold_compound.pf / RNA.pf_fold / 任何触发 McCaskill 的调用
    subopt   : fold_compound.subopt
    eval     : fold_compound.eval_structure 等 O(L) 查表（极便宜，单独记，不并入预算主轴）
    pr/ned   : pr_structure / ensemble_defect（需要 pf 已算过；若内部触发 pf 由 pf 计数捕获）
    sample   : pbacktrack（采样）
    inverse  : RNA.inverse_fold / inverse_pf_fold（内部自己调折叠，另记）

mfe-等效折算在报表阶段做（harness/cost_model.json 由 calibrate_cost.py 标定），
这里只保证**原始次数不丢**。
"""

from __future__ import annotations

import atexit
import json
import os
import threading
import time
from collections import Counter

import RNA

_LOCK = threading.Lock()
_INSTALLED = False
_ORIG: dict = {}

# 全局计数（install 模式）；FoldCounter 另有自己的栈式快照
COUNTS: Counter = Counter()
WALL: Counter = Counter()
LENGTH_HIST: Counter = Counter()

# (属主, 属性名, 计数类别)。属主为 None 表示 RNA 模块本身。
_TARGETS = [
    (None, "fold", "mfe"),
    (None, "pf_fold", "pf"),
    (None, "inverse_fold", "inverse"),
    (None, "inverse_pf_fold", "inverse"),
    ("fold_compound", "mfe", "mfe"),
    ("fold_compound", "mfe_window", "mfe"),
    ("fold_compound", "subopt_zuker", "mfe"),
    ("fold_compound", "pf", "pf"),
    ("fold_compound", "pf_window", "pf"),
    ("fold_compound", "subopt", "subopt"),
    ("fold_compound", "eval_structure", "eval"),
    ("fold_compound", "eval_structure_pt", "eval"),
    ("fold_compound", "pr_structure", "pr"),
    ("fold_compound", "ensemble_defect", "ned"),
    ("fold_compound", "pbacktrack", "sample"),
    ("fold_compound", "pbacktrack5", "sample"),
]


def _seq_len(args) -> int:
    for a in args:
        if isinstance(a, str) and a and set(a.upper()) <= set("ACGUTN&"):
            return len(a)
    try:  # fold_compound self
        return int(getattr(args[0], "length", 0) or 0)
    except Exception:
        return 0


def _wrap(fn, kind):
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            with _LOCK:
                COUNTS[kind] += 1
                WALL[kind] += dt
                n = _seq_len(args)
                if n:
                    LENGTH_HIST[f"{kind}:L{n}"] += 1

    wrapper.__name__ = getattr(fn, "__name__", kind)
    wrapper.__doc__ = getattr(fn, "__doc__", None)
    wrapper._foldcount_wrapped = True
    return wrapper


def install(dump_at_exit: str | None = None) -> None:
    """给 RNA 模块与 fold_compound 打补丁。重复调用安全。"""
    global _INSTALLED
    if _INSTALLED:
        if dump_at_exit:
            atexit.register(dump, dump_at_exit)
        return
    for owner, attr, kind in _TARGETS:
        obj = RNA if owner is None else getattr(RNA, owner, None)
        if obj is None:
            continue
        fn = getattr(obj, attr, None)
        if fn is None or getattr(fn, "_foldcount_wrapped", False):
            continue
        try:
            setattr(obj, attr, _wrap(fn, kind))
            _ORIG[(owner, attr)] = fn
        except (AttributeError, TypeError):
            # SWIG 某些属性只读 —— 记下来，报表里要诚实标注未覆盖项
            COUNTS[f"_unpatchable:{owner}.{attr}"] += 0
    _INSTALLED = True
    if dump_at_exit:
        atexit.register(dump, dump_at_exit)


def uninstall() -> None:
    global _INSTALLED
    for (owner, attr), fn in _ORIG.items():
        obj = RNA if owner is None else getattr(RNA, owner)
        setattr(obj, attr, fn)
    _ORIG.clear()
    _INSTALLED = False


def snapshot() -> dict:
    with _LOCK:
        return {
            "counts": dict(COUNTS),
            "wall_sec": {k: round(v, 6) for k, v in WALL.items()},
            "by_length": dict(LENGTH_HIST),
        }


def reset() -> None:
    with _LOCK:
        COUNTS.clear()
        WALL.clear()
        LENGTH_HIST.clear()


def dump(path: str, extra: dict | None = None) -> dict:
    rec = snapshot()
    rec["rna_version"] = RNA.__version__
    rec["pid"] = os.getpid()
    rec["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if extra:
        rec.update(extra)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
    return rec


class FoldCounter:
    """上下文管理器：进入时打补丁并归零增量，退出时给出本段增量。"""

    def __init__(self):
        self.result: dict | None = None
        self._base: dict | None = None

    def __enter__(self) -> "FoldCounter":
        install()
        self._base = snapshot()
        return self

    def __exit__(self, *exc) -> bool:
        now = snapshot()
        base = self._base or {"counts": {}, "wall_sec": {}, "by_length": {}}
        self.result = {
            sec: {
                k: now[sec].get(k, 0) - base[sec].get(k, 0)
                for k in set(now[sec]) | set(base[sec])
                if now[sec].get(k, 0) - base[sec].get(k, 0)
            }
            for sec in ("counts", "wall_sec", "by_length")
        }
        return False

    # 便捷访问
    @property
    def counts(self) -> dict:
        return (self.result or {}).get("counts", {})

    def dump(self, path: str, extra: dict | None = None) -> dict:
        rec = dict(self.result or {})
        rec["rna_version"] = RNA.__version__
        if extra:
            rec.update(extra)
        with open(path, "w") as fh:
            json.dump(rec, fh, indent=2, sort_keys=True)
        return rec
