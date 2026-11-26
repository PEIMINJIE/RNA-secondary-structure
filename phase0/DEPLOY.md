# RNA 逆设计项目 — 部署记录与使用说明

> 部署日期：2026-11-24 · 机器：HiPerGator · 根目录 `/path/to/RNA`
> 配套：`baseline_plan.md`（baseline 与统一评测协议）、`experiment_plan.md`（完整实验计划）
> 命名约定：外部通用语言模型一律用别名 **QW** / **DS**。真实 HF id 只在 `models/vendor_map_private.json`（不要进 git、不要上传、不要贴进对话）。

---

## 1. 目录结构

```
RNA/
├── baseline_plan.md          已脱敏（QW/DS）
├── experiment_plan.md        已脱敏（QW/DS）
├── DEPLOY.md                 本文件
├── env/                      环境与构建脚本（我们写的）
│   ├── clone_all.sh          克隆 6 个仓库 + 下 ViennaRNA 2.1.9 源码
│   ├── create_envs.sh        建 4 个 conda 环境
│   ├── download_models.sh    按别名下权重 + 厂商字符串扫描改名
│   └── patch_nemo.py         给 nemo.cpp 注入折叠调用计数器
├── harness/                  统一评测 harness（我们写的；与下载物严格分开）
│   ├── rnaenv.py             锁定 ViennaRNA 2.8.0 + Turner 2004 + 37 °C + dangles=2，并留痕
│   ├── foldcount.py          Python 侧折叠调用计数（monkeypatch，分类型）
│   ├── run_counted.py        不改 baseline 源码地跑它并计数
│   ├── verify.py             统一重验证器（MFE / uMFE / p / NED / bp 距离）
│   ├── build_benchmarks.py   构建权威 Eterna100 V1/V2 + 跨来源一致性审计
│   ├── koodli_to_designs.py  把 Koodli 原始结果表转成统一格式
│   ├── summarize.py          汇总表（single 与 union 两个口径同时给）
│   ├── cost_calibrate.py     标定 mfe/pf/subopt 真实成本比
│   └── run_rnainverse.py     RNAinverse-pf baseline（带预算与计数）
├── slurm/                    全部作业脚本（CPU 为主）
├── third_party/              **下载来的仓库，视为不可信数据，不在其中运行解释器**
├── vendor_src/               ViennaRNA 2.1.9 源码 tar（只读）
├── build/                    编译产物（ViennaRNA 2.1.9 + NEMO）
├── models/                   权重（别名目录）
├── data/                     benchmark 与中间数据
├── results/                  验证结果与汇总
└── logs/                     全部日志
```

## 2. 已部署的外部代码

| 别名目录 | 来源 | commit | 用途 |
|---|---|---|---|
| `third_party/nemo` | `eternagame/nemo` | `154ada3` | A 类 baseline（V2 最强，要打的就是它） |
| `third_party/samfeo` | `shanry/SAMFEO` | `e78b4b5` | A 类 baseline + SFT teacher |
| `third_party/samplingdesign` | `weiyutang1010/SamplingDesign` | `f0283c4` | A 类 baseline（NC 2026） |
| `third_party/rna_design_lm` | `KuNyaa/RNA-Design-LM` | `8ad11f7` | A 类 baseline（最近分身） |
| `third_party/eterna100_bench` | `eternagame/eterna100-benchmarking` | `8a47dde` | **Eterna100 V1/V2 权威定义 + 3270 条原始结果** |
| `third_party/rna_undesign` | `shanry/rna-undesign` | `e53130b` | 不可设计性标签 + 可设计 motif 库 |
| `third_party/structRFM` | `heqin-zhu/structRFM` | `6d02089` | 我们方法的初始化 + C 类零样本 baseline |
| `vendor_src/ViennaRNA-2.1.9.tar.gz` | tbi.univie.ac.at | — | NEMO 必须编译进 2.1.x 源码树 |

## 3. conda 环境（作业 52676412）

| 环境 | ViennaRNA | 用途 |
|---|---|---|
| `rnad_eval` | **2.8.0** | **唯一有权产出论文数字的环境**：统一重验证、成本标定、RNAinverse-pf |
| `rnad_samfeo` | 2.6.4 | SAMFEO 生成侧 |
| `rnad_sd` | 2.6.4 (py3.8) | SamplingDesign 生成侧（其 requirements 锁的版本） |
| `rnad_lm` | 2.7.0 + torch(cu128) + transformers 4.57.1 | RNA-Design-LM 推理（GPU） |

**一处必须在论文里交代的偏离**：RNA-Design-LM 的 `requirements.txt` 锁 `torch==2.4.0`（cu121），
但本集群 GPU 是 B200（sm_100），cu121 轮子根本跑不起来 → 换 cu128 的新 torch。
只影响推理，不动权重。GPU 作业里还要 `module load cuda/12.8.1`。

## 4. 已提交的作业

| JobID | 脚本 | 做什么 |
|---|---|---|
| 52676412 | `slurm/00_create_envs.sbatch` | 建 4 个 conda 环境（含计算节点出网探测） |
| 52676596 | `slurm/01_build_nemo.sbatch` | 编 ViennaRNA 2.1.9 + 打了计数器补丁的 NEMO，并冒烟 |
| 52676656 | `slurm/02_harness_smoke.sbatch` | harness 自检 + **Koodli 3270 条原始序列在我们环境下重验证** |
| 52676739 | `slurm/03_build_samplingdesign.sbatch` | 编 SamplingDesign 的 C++ 采样器 + 冒烟 |
| 52676740 | `slurm/04_download_models.sbatch` | 下 3 份权重到别名目录 + 厂商字符串扫描 |
| 52676798 | `slurm/10_smoke_baselines.sbatch` | RNAinverse-pf / SAMFEO / NEMO 的「能跑 + 能计数」冒烟 |

全部 CPU、`--qos=YOUR_BURST_QOS`、显式 `--time`、排除坏节点 `c0706a-s23`，无 GPU 作业。

## 5. 统一评测协议的落地方式

`harness/rnaenv.py` 锁定：ViennaRNA 2.8.0 / Turner 2004（显式 `params_load_RNA_Turner2004`）/ 37 °C /
`dangles=2` / `noLonelyPairs=0`，每个结果文件旁边都写一份 `provenance.json`（含版本、主机、作业号）。

**NEMO 的能量参数问题已查清**：`nemo.cpp:721` 的 `config_eterna()` 才会去读 `vrna185x.par`（Turner 1999）
并把 `dangles` 设成 1，而它**只在传 `-E` 时被调用**。
所以 **不传 `-E` 就是 ViennaRNA 2.1.9 内置默认 = Turner 2004 + dangles=2**，正是我们要的设定。
`baseline_plan.md §2.1`「必须换成 Turner 2004 参数」可以改成「不要传 `-E`」。补丁里顺手打印了
`ENV: params=builtin_Turner2004 dangles=%d` 留痕。

**折叠调用计数**：
- Python 侧（SAMFEO、RNAinverse、RNA-Design-LM 的验证部分）：`harness/foldcount.py` 分类型计数
  （mfe / pf / subopt / eval / pr / ned / sample / inverse），用 `harness/run_counted.py` 包住即可，不改 baseline 源码。
- NEMO（C++）：`env/patch_nemo.py` 注入计数器，3 个调用点全包住（`normal_score` 的 `fold` 与
  `energy_of_structure`、主循环的 `fold`），`atexit` 时打印 `CNT:` 并写 `NEMO_COUNT_FILE`。
- mfe-等效折算比由 `harness/cost_calibrate.py` 实测得到，不靠拍脑袋。

## 6. 部署中查清的事（直接影响两份计划）

1. **`eterna100_bench/data/results.tsv` 含 3270 条原始设计序列**（算法 × 变体 × vienna1/vienna2 × trial ×
   序列 × 时间 × 成功标记）。这不是论文里被抽取过的表格数字，而是原始序列 →
   可以在我们自己的环境下重验证。`baseline_plan.md §6` 的待核 #1–#3（NEMO 在 V2 上到底是不是 86）
   **不需要再去抓 PDF**，作业 52676656 直接给答案，而且顺带给出 uMFE 与 p 的分布。
2. **`samplingdesign/data/eterna100_v2.txt` 只有 19 行** —— 它只放了 V2 相对 V1 改过的那批结构，
   不是完整 100 题。`build_benchmarks.py` 的审计会把这件事写进 `data/eterna100/source_audit.json`。
   权威来源只认 `eterna100_bench/data/eterna100_puzzles.tsv`。
3. **SamplingDesign 的内层折叠不是 ViennaRNA**：它用自己的 beam 版 partition function
   （LinearPartition 系，默认 `beamsize=250`，近似），只在验证时调 ViennaRNA。
   → `baseline_plan.md §1.2` 现在只写了「Python monkeypatch」和「NEMO 插计数器」两种，
   **缺第三种**：SamplingDesign 需要按「步数 × beam」单独核算，或在其 C++ 里插计数器。这是待办。
4. **SamplingDesign 自报：Eterna100 全套在 64 核上约 10 天**（README §Run all structures）。
   Phase 0 的 CPU 预算要按这个量级估，不是按小时。
5. **NEMO 的每次 playout 就是一次完整 `fold()`**：`nested()` → `sample()` → `normal_score()` → `fold()`，
   而 playout 循环带 `#pragma omp parallel for`。两个后果：
   (a) 计数器必须 `omp atomic`，否则并行丢数（第一版补丁在 L=16 上只数到 7 次 fold，真实量级在 10² 以上，
       已在作业 52677258 修掉）；
   (b) NEMO 的预算天然是「迭代数 × 每迭代 playout 数 × 每 playout 一次 O(L³) fold」，
       这正是 `solved@B` 想量的东西 —— 它的 24 小时单核就花在这里。
   (c) **NEMO 的搜索结果依赖线程数**：playout 循环里的 RNG 不是线程安全的，实测同一道题
       `OMP_NUM_THREADS=1` 用 21 次 fold、8 线程用 60 次。正式跑必须钉死 `OMP_NUM_THREADS`（建议 1），
       否则 seed 不能复现，预算数也不可比。
   顺带：`quick_score()` 是作者弃用的快速近似（注释说成功率掉约 1/3），现在是死代码。
6. **RNAinverse 的内部折叠计数不到**：`RNA.inverse_fold` / `inverse_pf_fold` 是 C 实现，
   内部成千上万次折叠对 Python monkeypatch 不可见。`harness/run_rnainverse.py` 因此两路计数：
   Python 可见次数 + wall-clock ÷ 标定单次 mfe 耗时的估计值，预算判定取 max，两个数都落盘。
   论文的预算定义里必须写清这一条。
7. **RNA-Design-LM 的权重与数据都在 HF 上**（含 1M 结构的 SL 训练数据与 11 个 parquet 分片）。
   §3.6 那个「半天就能做」的结构覆盖度 motivation 实验所需的数据，不用自己复现它们的生成脚本。
   本次只下了模型与测试集，训练数据按需再下。

### 6.1 首批实测结果（作业 52676656，2026-11-24）

**A. 官方 sample solution 在我们环境下的自检**（统一 2.8.0 + Turner 2004 + dangles=2）

| benchmark | MFE 命中 | uMFE | 未命中 |
|---|---|---|---|
| V1 | **81/100** | 70 | 正好是 V1↔V2 结构不同的那 19 题：50,52,57,60,61,67,78,80,81,86,87,88,90,91,92,96,97,99,100 |
| V2 | **99/100** | 83 | 只有 #100 |

两条独立印证：
- V1 在 Turner 2004 下的天花板 ≈ **82** —— 官方解自己就只有 81 题能命中，且失手的正是 V2 要改掉的那 19 题。
  `baseline_plan.md §5` 的「可达分母 82」不再是二手引用。
- V2 在 Turner 2004 下**基本全可解**（99/100 官方解直接命中），与 Koodli 正文「100 of 100 solvable in Vienna 2」一致。
  #100 需要单独查（可能是引擎相关的解）。

**B. 折叠调用成本比（实测，harness/cost_model.json）**

| 比值 | 中位数 | 说明 |
|---|---|---|
| pf / mfe | **1.74** | L=30 时 1.60，L=400 时 2.12（随长度上升） |
| subopt(δ=0) / mfe | **1.03** | 证实 `experiment_plan.md` 实测 #10：subopt(0) 几乎不比 mfe 贵 |
| eval_structure / mfe | 0.006 | 可忽略，不进预算主轴 |
| pr / ned / sample（pf 之后）| ~0 | 可忽略 |

L=400 时单次 mfe = 186 ms，单次 pf = 394 ms —— 这是「24 小时单核」能买到多少次调用的换算基准。

**C. Koodli 的 3270 条原始序列已在我们环境下重验证完**（`results/koodli_verified.jsonl`，3270 条全部匹配上题号）。
首轮汇总把 V1/V2 和 vienna1/vienna2 混在一起了（`verify.py` 当时没把 `benchmarks`/`gen_engine` 带下去），
已修并重跑（作业 52679896）。首轮里 **NEMO(2500 iter) = MFE 86 / uMFE 77** 与文献的 86 吻合，
但要等分组版确认它是 V2-only。另外首轮出现了一个比 86 更高的方法（**DesiRNA 92/89**），
如果分组后在 V2 上仍然成立，`baseline_plan.md §5` 的「V2 最强是 NEMO 86、空间 14 题」这个前提就要重写 ——
**这是当前最需要确认的一件事**。

**D. baseline 的预算口径已实测出来**

| 方法 | 100 步/迭代实际消耗 | 含义 |
|---|---|---|
| SAMFEO | `pf 110 + pr 110 + mfe 1` | 成本**由 pf 主导**，1 step ≈ 1.1 次 pf ≈ 1.9 mfe-等效。step→预算 的换算有了实测依据，不用猜 |
| RNAinverse-pf | Python 可见 2 次，估计 120 次 | 证实 C 内部折叠对 monkeypatch 不可见，两路计数（可见 + wall-clock÷标定成本）是必须的 |
| NEMO | L=16: 7 次 fold；L=17: 21（1 线程）/ 60（8 线程）| 每次 playout 一次完整 fold；线程数必须钉死 |

**E. SAMFEO 自带的 `data/eterna/eterna100.txt` 是 Eterna100-V1**（无题号列，按结构内容比对：V1 100/100，V2 81/100）。
它不含 V2，跑 V2 要喂我们 `data/eterna100/eterna100_v2.jsonl` 里的结构。

**F. Koodli 表里 RNAinverse 只解出 20 题**（汇总口径待分组确认），远低于文献的 77/82 ——
说明他们的 RNAinverse 是在很小的预算下跑的。`baseline_plan.md §6` 待核 #2 的「82 很反常」要去 RNA-Design-LM 的表里核，
不是 Koodli 的表。

## 7. 怎么用

```bash
module load conda && conda activate rnad_eval

# 1) 构建 benchmark（已由作业 52676656 跑过一次）
python -I harness/build_benchmarks.py

# 2) 验证任意方法的产出（jsonl 每行需要 target_structure + designed_sequence）
python -I harness/verify.py --in <designs.jsonl> --out <verified.jsonl> \
       --provenance <provenance.json>

# 3) 汇总（single 与 union 两个口径）
python -I harness/summarize.py --in <verified.jsonl> --out <summary.csv>

# 4) 跑 RNAinverse-pf（固定预算、单次运行、指定 seed）
python -I harness/run_rnainverse.py --bench data/eterna100/eterna100_v2.jsonl \
       --out results/rnainverse_pf_v2_seed0.jsonl --mode pf --budget 100000 --seed 0

# 5) 跑任意 Python baseline 并计数（例：SAMFEO）
conda activate rnad_samfeo
echo "(((((......)))))" | python -I harness/run_counted.py \
       --counts results/samfeo_counts.json --cwd third_party/samfeo \
       -- third_party/samfeo/main.py --online --step 100

# 6) 跑 NEMO（Turner 2004 = 不传 -E）
export NEMO_COUNT_FILE=results/nemo_counts.jsonl
cd build/ViennaRNA-2.1.9/nemo && ./nemo -i 2500 "<target>"
```

## 8. 已知缺口 / 待办

| # | 事项 | 状态 |
|---|---|---|
| 1 | SamplingDesign / DesiRNA 的折叠调用计数 | **部分解决**：改用「墙钟 ÷ 本长度标定的单次 mfe 耗时」估计，并在每条记录里存 `fold_calls_counted=null` + `fold_calls_estimated` + `cost_note`，论文里如实标注是估计值。要精确值仍需在 SamplingDesign 的 C++ 里插计数器 |
| 2 | 正式 solved@B 曲线（5 方法 × 100 题 × 5 seed） | ✅ **已跑完**（2026-11-25）：`slurm/42_campaign_v2.sbatch`，2 500 次运行、325 核时，结果见 `README.md` §5.1、产物 `results/solvedB/`。<br>用的就是「一次跑到 B_max 并记录首次命中成本」的省法：任意 B ≤ B_max 的 solved@B 从同一批运行里读出（`harness/solved_at_b.py`、`campaign_wall_curve.py`），未命中按右删失处理。 |
| 2b | ❗**截尾不对称**（闸响时只有 NEMO 留下候选序列） | **未修**，是正式跑之前的第一优先级。实测见 `harness/censoring_audit.py` / `README.md` §5.3：SAMFEO 276、SamplingDesign 403、RNAinverse 120、DesiRNA 80 次运行被判负而我们从未看过它们的候选 → 这四个方法的数字都是下界。修法要她定（`README.md` §8 #2） |
| 2c | DesiRNA 的墙钟预算泄漏 | 外层 `subprocess` 的保命超时是 `time_limit + 120 s`，而它只在迭代边界检查 `-t` → 有一部分命中用掉了 900–1 020 s。严格 900 s 截断下它是 63.2±1.6，不截断是 73.8±1.6。正式跑时把保命超时收到 `+5 s` |
| 3 | RNA-Design-LM 的 GPU 推理 | 环境已建、权重在下；按当前 GPU 使用约定，等你发话再提交 GPU 作业 |
| 4 | Rfam-Learn-Train 65,000 条仍锁在 rnainvbench 的 pickle 里 | 需要你明确授权加载（`experiment_plan.md §8#4`） |
| 5 | 权重内部的厂商字符串 | `config.json` / `tokenizer_config.json` 里的 `architectures` / `model_type` 是加载必需，改了模型就加载不了 → 保留并在 `models/vendor_string_scan.json` 里逐条记录；我们自己的目录名、脚本、作业名、文档一律别名 |
| 6 | 各 baseline 仓库 license 是否允许重分发其输出 | 未查（湿实验要合成它们的设计序列，`experiment_plan.md §9` 也点了这条） |
| 7 | git 仓库 | 本目录还不是 git repo；要不要 `git init` 只管 `harness/ env/ slurm/ *.md`（third_party / models / data / logs 排除）等你定 |

## 9. 脱敏策略（2026-11-24 用户确认）

**规则范围**：只管**商业大模型厂商名**（QW / DS / GM 这一类）。
学术 RNA 模型（structRFM、RNA-FM、RNA-MSM、CocoRNA、BPfold 等）按**真名**引用 —— 否则论文的引用和方法命名写不了。

**third_party 保持原样**：下载来的上游代码不改。它不随任何交付物分发；
structRFM 仓库里有 9 处提到两个**名字里带商业架构名**的学术 RNA 模型（README + 两处注释；
具体命中位置见 `reports/devendor_report.json`，这里不复写全称），按用户决定**不动**，
改了会把上游的 GitHub 链接改坏、也丢掉溯源。检查脚本把这些标成 ⚠️（信息性），只在**我们自己的文件**命中时才失败。

### 9.1 ⚠️ 一个会骗人的陷阱：交互 shell 的 grep 不可信

交互 shell 里的 `grep` 是 **ugrep 包装函数**，带 `--ignore-files`，**会尊重 .gitignore**。
本项目 .gitignore 里有 `third_party/ models/ data/ logs/ build/ vendor_src/` ——
所以直接 `grep -r "..." .` 会**静默跳过这些目录**，给出假阴性（部署初期就被骗过一次）。

正确做法（两条都要）：
```bash
command grep -rnIE -f env/vendor_patterns.txt .    # 绕过包装函数，用真 GNU grep
python -I env/devendor.py --scan                   # 自己遍历文件，完全不依赖 grep
bash env/check_no_vendor.sh                        # 上面两条一起跑，交付前的硬门禁
DEEP=1 bash env/check_no_vendor.sh                 # 连二进制也用 strings 过一遍
```
sbatch 作业里的 shell 是非交互的，`grep` 就是真 GNU grep，不受影响。

### 9.2 脱敏基础设施

| 文件 | 作用 |
|---|---|
| `env/vendor_patterns.txt` | 检测用正则，覆盖 30+ 个商业厂商名（含中文名）。**模式本身写成 `q[w]en` 这种单字符字符类**，所以这个文件自己不含任何完整名，却照样命中 |
| `env/vendor_alias_rules.json` | 改写规则（厂商名 → 别名），同样用字符类写法 |
| `env/devendor.py` | `--scan` 扫描 / `--apply` 改写 / `--deep` 连二进制；报告里命中字符串**一律掩码**（`Q***`），报告文件自己不会变成新的泄漏点 |
| `env/check_no_vendor.sh` | 交付前硬门禁：我们自己的文件有命中就 exit 1 |
| `harness/load_lm.py` | 权重目录里 `architectures` / `model_type` / `tokenizer_class` 被改成别名后，transformers 认不出来；本模块从私有映射拼出真实类名，**只在内存里**还原再加载，磁盘保持别名 |
| `models/vendor_map_private.json` | 唯一允许出现真实 HF id 的地方；敏感项按 `hf_id_parts` 拆开存（拼接后才是真实 id），所以连它也扫不出完整名。不进 git、不上传 |

**基座 QW 模型本次不下载**（`download: false`）：它只服务 §3.5 的初始化消融（Phase 3+），
而它的 config/tokenizer 里厂商字符串最多。等真要做消融时再下，并立刻 `devendor.py --apply`。

**当前扫描结果**：我们自己的文件 **0 处**命中；third_party 9 处（按决定保留）；白名单 0 处。
