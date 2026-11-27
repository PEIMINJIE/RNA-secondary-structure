"""在不改动 baseline 源码的前提下运行它，并统计全部 ViennaRNA 调用。

    python -I harness/run_counted.py --counts out/counts.json -- \
           /path/to/baseline/main.py --online --step 100

机制：先 install() 打补丁，再用 runpy 以 __main__ 身份执行目标脚本，
目标脚本所在目录被显式放到 sys.path[0]（它要 import 自己的 utils/）。
退出时（含正常退出与异常）把计数落盘。
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", required=True, help="计数输出 json")
    ap.add_argument("--counts-prefix", default="",
                    help="周期性落盘前缀；每个进程写 <prefix>.<pid>.json。"
                         "多进程 baseline（DesiRNA 的 mp.Pool）必须给，否则子进程的计数会丢")
    ap.add_argument("--flush-every", type=int, default=200, help="每多少次折叠落盘一次")
    ap.add_argument("--limit", type=int, default=0,
                    help="折叠预算安全网（mfe+pf+subopt 超了就抛 FoldBudgetExceeded）；0 = 不限")
    ap.add_argument("--cwd", default="", help="运行前切到该目录（baseline 常假设自己的工作目录）")
    ap.add_argument("--tag", default="", help="写进计数文件的标签")
    ap.add_argument("rest", nargs=argparse.REMAINDER, help="-- 之后：目标脚本与它的参数")
    args = ap.parse_args()

    rest = args.rest
    if rest and rest[0] == "--":
        rest = rest[1:]
    if not rest:
        ap.error("缺少目标脚本（用 -- 分隔）")

    target, targs = rest[0], rest[1:]
    target = os.path.abspath(target)
    if not os.path.isfile(target):
        ap.error(f"目标脚本不存在: {target}")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import foldcount  # noqa: E402
    import rnaenv  # noqa: E402

    # baseline 自己的目录要能 import
    sys.path.insert(0, os.path.dirname(target))
    if args.cwd:
        os.chdir(args.cwd)

    foldcount.install()
    if args.counts_prefix or args.limit:
        foldcount.configure(prefix=args.counts_prefix or None,
                            flush_every=args.flush_every,
                            limit=args.limit,
                            extra={"tag": args.tag, "argv": targs})
    sys.argv = [target] + targs
    rc = 0
    try:
        runpy.run_path(target, run_name="__main__")
    except foldcount.FoldBudgetExceeded as e:
        print(f"[run_counted] 预算闸响了: {e}", file=sys.stderr)
        rc = 7           # 约定：7 = 折叠预算用尽（不是崩溃）
    except SystemExit as e:
        rc = int(e.code or 0)
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 1
    finally:
        os.makedirs(os.path.dirname(os.path.abspath(args.counts)) or ".", exist_ok=True)
        rec = foldcount.dump(args.counts, {
            "tag": args.tag,
            "target": target,
            "argv": targs,
            "env": rnaenv.provenance(),
        })
        print(f"[run_counted] counts={rec.get('counts')} -> {args.counts}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
