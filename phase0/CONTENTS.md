# 这个目录里是什么

Phase 0（五个 A 类 baseline 的统一评测）的**全部自研代码、作业脚本、基准集和结果汇总**。
`README.md` 是 Phase 0 的报告本体，`ANSWERS_campaign_spec_v2.md` 是对 `campaign_spec.md` v2 的逐条答复。

```
phase0/
├── README.md                     Phase 0 报告（按 baseline_plan.md / experiment_plan.md 的章节号对位）
├── ANSWERS_campaign_spec_v2.md   对 campaign_spec.md v2 的逐条答复（含你 §7 要的完整命令行）
├── RESOURCES.md                  机时/CPU/内存：预测 vs 实测，以及 24 h 档的外推
├── DEPLOY.md                     部署与运行记录，附未解决问题清单
├── CONTENTS.md                   本文件
├── harness/                      统一评测 harness（自研，17 个脚本 + 1 份标定表）
│   ├── build_benchmarks.py       从四个上游仓库各自的拷贝交叉审计出权威 Eterna100 V1/V2
│   ├── rnaenv.py                 钉死能量模型：Turner 2004 + 37 °C + dangles=2 + noLP=0
│   ├── foldcount.py              折叠调用计数器，分类型（mfe/pf/subopt/eval/pr/ned/sample/inverse）
│   ├── run_counted.py            不改上游源码地给任意 Python 脚本套上计数器
│   ├── run_campaign.py           五个方法的统一驱动（预算闸、截尾记录、provenance）
│   ├── run_rnainverse.py         RNAinverse-pf baseline（带预算的单题求解器）
│   ├── verify.py                 统一重验证：ViennaRNA 2.8.0 下重算 MFE 判据和 uMFE 判据
│   ├── solved_at_b.py            solved@B 曲线
│   ├── agg_campaign.py           把 verified（判据）和 raw（预算/截尾）按 (seed, id) 合起来
│   ├── campaign_wall_curve.py    墙钟轴 + 折叠轴的 solved@B，逐题成本
│   ├── censoring_audit.py        截尾对称性审计（你 §5.1 那张表就是它出的）
│   ├── cost_calibrate.py         单次折叠耗时标定 → cost_model.json
│   ├── koodli_budget_curve.py    Koodli 等人的公开数据重验证 + 预算曲线
│   └── ...                       其余为汇总与小工具
├── env/                          上游克隆、conda 环境、NEMO 补丁
│   ├── clone_all.sh              固定 commit 地克隆五个上游仓库
│   ├── create_envs.sh            建 rnad_eval / rnad_samfeo / rnad_sd 三个环境
│   └── patch_nemo.py             给 NEMO 加 omp atomic 折叠计数器 + 预算闸
├── slurm/                        26 个作业脚本，按编号就是执行顺序
├── data/
│   ├── eterna100/                权威 V1/V2（各 100 题）+ 交叉审计报告
│   ├── desirna/published.jsonl   DesiRNA 论文公布的序列（用于核对它的自报数字）
│   └── koodli/designs.jsonl      Koodli 等人公开的设计结果（用于文献数字重验证）
└── results/                      我们自己的结果（只含汇总与逐题证据，不含上游中间产物）
    ├── solvedB/                  正式 campaign：5 方法 × 5 seeds × 100 题
    │   ├── campaign_fold_curve.csv / campaign_wall_curve.csv
    │   ├── per_puzzle_cost.csv
    │   └── <method>_v2_B100000/seed{0..4}_chunk{0..4}.{jsonl,verified.jsonl,provenance.json}
    ├── koodli_verified.jsonl     3270 条公开设计在 2.8.0 下的重验证结果
    ├── koodli_summary.csv        文献数字 vs 我们重验证的对照
    └── ...
```

每个 `seed*_chunk*.jsonl` 是**原始**产出（含 `stop_reason` / `wall_sec` / `censored`，截尾分析要用它），
同名的 `.verified.jsonl` 是在 ViennaRNA 2.8.0 下重验证后的权威判据，
`.provenance.json` 记了那一次运行的环境指纹（ViennaRNA 版本、能量参数、温度、dangles、节点、作业号）。

> 注意：`verify.py` 只透传一个白名单字段集，**不带 `stop_reason` / `wall_sec`**。
> 所以任何涉及预算或截尾的分析都必须把 verified 和 raw 按 `(seed, id)` join 回去——
> `harness/agg_campaign.py` 就是干这个的。我们一开始漏了这步，得到过「撞预算 0 次」的假结论。

---

## 没有放进来的东西，以及为什么

| 不在包里 | 体积 | 原因 |
|---|---|---|
| `third_party/` 五个上游仓库 | 629 M | 用 `env/clone_all.sh` 按固定 commit 自己克隆，比收一份拷贝更可靠 |
| `build/`（ViennaRNA 2.1.9、打过补丁的 NEMO 二进制、SamplingDesign） | 77 M | 编译产物，跟机器绑定；用 `slurm/01_*` `slurm/03_*` 重建 |
| `models/` 权重 | 3.0 G | Phase 2 才用到，Phase 0 一次都没加载 |
| `logs/` 作业日志 | 1.1 M | 只有节点名和路径，没有结论性内容 |
| `results/solvedB/*/_work_*/` | 1.1 G | 上游工具自己写的中间文件（SAMFEO 单个结果 json 就有 9 M） |
| 内部命名规范的工具链与那张私有映射表 | — | 和 Phase 0 的科学内容无关，按约定不外发（`README.md` 开头第 5 行的那条约定） |
| `harness/load_lm.py` | — | 依赖上面那张映射表，且属 Phase 2 |

SAMFEO 的分类型折叠计数文件（`samfeo_counts_*.json`，229 个）在 `_work_*` 里，所以也没进来。
`ANSWERS_campaign_spec_v2.md` §4 里贴了它的格式和一个典型值；要全量的话说一声，单独打包。

---

## 路径

所有脚本里的绝对路径已经换成占位符 **`/path/to/RNA`**，Slurm 的 QOS / account 换成
`YOUR_QOS` / `YOUR_BURST_QOS` / `YOUR_ACCOUNT`。在自己的机器上跑之前全局替换这几个就行：

```bash
grep -rl '/path/to/RNA' . | xargs sed -i "s#/path/to/RNA#$PWD#g"
```

---

## 从零复现一遍

```bash
# 1. 上游代码（固定 commit）与三个 conda 环境
bash env/clone_all.sh
sbatch slurm/00_create_envs.sbatch

# 2. 编译：ViennaRNA 2.1.9（NEMO 要这个版本）+ 打补丁的 NEMO + SamplingDesign
sbatch slurm/01_build_nemo.sbatch
sbatch slurm/03_build_samplingdesign.sbatch

# 3. 从四个上游拷贝交叉审计出权威基准集，并自检
sbatch slurm/02_harness_smoke.sbatch

# 4. 文献数字重验证（Koodli 等人的公开数据 → 预算曲线）
sbatch slurm/02b_reverify_koodli.sbatch
sbatch slurm/02c_budget_curve.sbatch

# 5. 正式 campaign：一个方法一次提交，5 seeds × 5 分块 = 25 个数组任务
for m in nemo rnainverse samfeo desirna samplingdesign; do
  export METHOD=$m FOLD_BUDGET=100000 TIME_LIMIT=900
  sbatch --export=ALL slurm/42_campaign_v2.sbatch
done

# 6. 汇总（每个数组任务结束时已自动跑过 verify.py）
sbatch slurm/44b_all_summary.sbatch
```

实测总花费 **324.7 核时**，无一例 OOM（2 G/进程，峰值 3–82 MB）。
逐方法的实测成本在 `RESOURCES.md` §4.0——**不要用 §4.2 那张预测表**，它按方法看偏差很大
（NEMO 高估 5 倍、RNAinverse 低估 6 倍），只有总量碰巧对上。

---

## 复现时会踩到的三个坑

1. **NEMO 必须 `OMP_NUM_THREADS=1`**。它 6 个 playout 选项走 OpenMP，而 RNG 不是线程安全的：
   同一道题 1 线程折 21 次、8 线程折 60 次。不钉死的话 seed 不可复现、预算数不可比。
2. **NEMO 不传 `-E` 才是 Turner 2004**（传了反而切到 1999）；**DesiRNA 必须显式传 `-p 2004`**，
   它的默认是 1999。
3. **`verify.py` 不透传 `stop_reason` / `wall_sec`**，见上面那条注意。
