"""给 nemo.cpp 打补丁，输出到构建目录（原仓库保持原样，它是下载来的不可信数据）。

三个补丁：
1. **折叠调用计数器**（必须 `omp atomic`：playout 在 `#pragma omp parallel for` 里，普通 ++ 会丢数）
2. **预算闸**：`NEMO_FOLD_LIMIT`（折叠调用预算，这是论文要的 B 轴）与 `NEMO_TIME_LIMIT`（墙钟秒）。
   为什么要内置而不是用 `timeout`：外部 SIGTERM 会让 atexit 不执行，**计数全丢**。
   闸在每次迭代开头检查，所以溢出不超过一次迭代的折叠数，而落盘的是精确计数。
3. **参数留痕**：`config_eterna()`（只在传 `-E` 时调用）才读 vrna185x.par（Turner 1999）+ dangles=1；
   不传 `-E` 就是 ViennaRNA 2.1.9 内置默认 = Turner 2004 + dangles=2 ← 我们要的设定。

用法：python -I env/patch_nemo.py <src nemo.cpp> <dst nemo.cpp>
"""

from __future__ import annotations

import sys

COUNTER_BLOCK = r'''
/* ---- 折叠调用计数器 + 预算闸（RNA 项目 harness 注入，2026-11-24）---- */
#include <stdlib.h>
#include <stdio.h>
#include <time.h>
static long long nemo_n_fold = 0;
static long long nemo_n_eval = 0;
static int       nemo_eterna_params = 0;
static long long nemo_fold_limit = 0;   /* NEMO_FOLD_LIMIT：折叠调用预算，0=不限 */
static double    nemo_time_limit = 0;   /* NEMO_TIME_LIMIT：墙钟上限（秒），0=不限 */
static time_t    nemo_t0 = 0;
static int       nemo_stop_reason = 0;  /* 0=正常结束 1=折叠预算用尽 2=墙钟到 */
static void nemo_inc_fold( void )
{
#ifdef _OPENMP
    #pragma omp atomic
#endif
    nemo_n_fold++;
}
static void nemo_inc_eval( void )
{
#ifdef _OPENMP
    #pragma omp atomic
#endif
    nemo_n_eval++;
}
static void nemo_dump_counts( void )
{
    double el = nemo_t0 ? difftime( time(NULL), nemo_t0 ) : 0.0;
    const char* path = getenv( "NEMO_COUNT_FILE" );
    if( path ) {
        FILE* f = fopen( path, "a" );
        if( f ) {
            fprintf( f, "{\"fold\": %lld, \"eval_structure\": %lld, \"params\": \"%s\", "
                        "\"dangles\": %d, \"stop_reason\": %d, \"elapsed_sec\": %.1f, "
                        "\"fold_limit\": %lld, \"time_limit\": %.1f}\n",
                     nemo_n_fold, nemo_n_eval,
                     nemo_eterna_params ? "vrna185x_Turner1999" : "builtin_Turner2004",
                     dangles, nemo_stop_reason, el, nemo_fold_limit, nemo_time_limit );
            fclose( f );
        }
    }
    printf( "CNT: fold=%lld eval_structure=%lld stop=%d elapsed=%.1f\n",
            nemo_n_fold, nemo_n_eval, nemo_stop_reason, el );
    fflush( stdout );
}
/* ---- end harness block ---- */
'''

PROVENANCE_BLOCK = r'''    {
        const char* fl = getenv( "NEMO_FOLD_LIMIT" );
        const char* tl = getenv( "NEMO_TIME_LIMIT" );
        if( fl ) nemo_fold_limit = atoll( fl );
        if( tl ) nemo_time_limit = atof( tl );
        nemo_t0 = time( NULL );
    }
    printf( "ENV: params=%s dangles=%d fold_limit=%lld time_limit=%.1f\n",
            nemo_eterna_params ? "vrna185x_Turner1999" : "builtin_Turner2004",
            dangles, nemo_fold_limit, nemo_time_limit );
    fflush( stdout );
'''

OLD_LOOP = """    for( ; iter; iter-- ) {
        strcpy( position, copy );"""

NEW_LOOP = """    for( ; iter; iter-- ) {
        /* 预算闸（harness 注入）：折叠调用预算或墙钟到了就跳出，让 atexit 正常落盘 */
        if( nemo_fold_limit > 0 && nemo_n_fold >= nemo_fold_limit ) { nemo_stop_reason = 1; break; }
        if( nemo_time_limit > 0 && difftime( time(NULL), nemo_t0 ) >= nemo_time_limit ) { nemo_stop_reason = 2; break; }
        strcpy( position, copy );"""

REPS = [
    (OLD_LOOP, NEW_LOOP),
    ("    double e = fold( position, secstr );",
     "    double e = ( nemo_inc_fold(), fold( position, secstr ) );"),
    ("    double es = energy_of_structure( position, target, 0 );",
     "    double es = ( nemo_inc_eval(), energy_of_structure( position, target, 0 ) );"),
    ("        e = fold( position, secstr );",
     "        e = ( nemo_inc_fold(), fold( position, secstr ) );"),
    ('    read_parameter_file("vrna185x.par");',
     '    read_parameter_file("vrna185x.par");\n    nemo_eterna_params = 1;'),
]

MAIN_ANCHOR = ("int main( int argc, char** argv )\n{\n"
               "    if( !parse_arguments( argc, argv ) ) return 1;\n")


def main() -> int:
    src, dst = sys.argv[1], sys.argv[2]
    s = open(src).read()
    if "nemo_dump_counts" in s:
        print("source already patched — 直接复制")
        open(dst, "w").write(s)
        return 0

    anchor = '#include "MEA.h"'
    assert anchor in s, "找不到 include 锚点"
    s = s.replace(anchor, anchor + "\n" + COUNTER_BLOCK, 1)

    for old, new in REPS:
        n = s.count(old)
        assert n == 1, f"匹配数异常 ({n}): {old[:60]!r}"
        s = s.replace(old, new, 1)

    assert MAIN_ANCHOR in s, "找不到 main 锚点"
    s = s.replace(MAIN_ANCHOR, MAIN_ANCHOR + "\n    atexit( nemo_dump_counts );\n" + PROVENANCE_BLOCK, 1)

    open(dst, "w").write(s)
    print(f"patched -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
