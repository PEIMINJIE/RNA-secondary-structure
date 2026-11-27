# 对 `campaign_spec.md` v2 的逐条答复

> 2026-11-25 · 对位你 2026-11-25 那份《Baseline Campaign 规格 v2》
> 本文件只回答能从 Phase 0 的代码和已落盘数据里**查得出来**的问题；查不出来的明确写「不知道，要你定」。
> 所有引用的代码都在本目录里，行号对应 `harness/run_campaign.py` 的当前版本。

---

## §7 你要的 DesiRNA 完整命令行 —— 这是你的优先级 #1，现在就能定

Phase 0 正式 campaign 里 DesiRNA 的调用是（`harness/run_campaign.py:245-251`，逐字）：

```
python third_party/desirna/DesiRNA.py \
    -f <单题输入文件> \
    -p 2004 \
    -sws on \
    -t 900 \
    -R 10 \
    -seed <seed>
```

外层包了 `subprocess.run(..., timeout=time_limit + 120)`。
Slurm 侧：`--cpus-per-task=1`、`--mem=2G`（`slurm/42_campaign_v2.sbatch`）。

逐条对你 §7 的表：

| 参数 | 默认值 | 我们实际传的 | 结论 |
|---|---|---|---|
| `-p/--param` | `1999` | **`2004`** | ✅ **你的 OOD 假设可以排除**。生成侧和评测侧都是 Turner 2004，不存在「1999 下优化、2004 下评分」 |
| `-sws/--stop_when_solved` | `off` | **`on`** | ✅ 解出即停是开着的 |
| `-r/--results_number` | **`10`** | **没传 → 用了默认 10** | ⚠️ **你的担心成立**。开了 sws 也要攒够 10 个解才退出，所以它在很多题上解出第 1 个之后继续烧预算 |
| `-R/--replicas` | `10` | **`10`** | ⚠️ 值对了，但**只给了 1 个核**（见下） |

### 所以 DesiRNA 比文献低约 8 题，有三个互相叠加的原因，都不是 Turner 1999

1. **`-r` 默认 10**：解出第一个解不停机。在墙钟预算下，这等于把预算的大部分花在「再找 9 个解」上。
2. **10 个 replica 挤 1 个核**：`-R 10` 会 `mp.Pool(10)`，但 Slurm 只给了 `--cpus-per-task=1`。
   10 个进程在单核上分时，**每个 replica 实际只拿到约 1/10 的墙钟**。
   你 §6 说「给 10 核，`-R` 保持 10」是对的——Phase 0 没给够，这条要改。
3. **外层 `+120 s` 宽限造成预算泄漏**：`timeout=-t + 120` 让 369 个命中里有 53 个用掉了 900–1020 s。
   按严格 900 s 口径重算，DesiRNA 从 **73.8 ± 1.6 掉到 63.2 ± 1.6**。
   正式跑要么把宽限压到 `+5 s`，要么（按你 §5.2）干脆换成步数驱动，墙钟只当保险丝。

### 其余四个方法的完整命令行（同样逐字）

| 方法 | 实际调用 | 备注 |
|---|---|---|
| NEMO | `nemo_bin -i 1000000 <target>`，环境变量 `NEMO_FOLD_LIMIT=B`、`NEMO_TIME_LIMIT=900`、`OMP_NUM_THREADS=1` | 不传 `-E` → Turner 2004。预算闸和计数器是我们给上游打的补丁，见 `env/patch_nemo.py` |
| SAMFEO | `python third_party/samfeo/main.py --online --step 90909`（= `int(B/1.1)`），target 走 stdin | 1 核 |
| SamplingDesign | `python <sd>/main --step 2000 --num_thread 1 --seed <s>` | ❗**步数是写死的 2000，没有跟 B 挂钩**；`--num_thread 1` 就是你 §6 指出的那条（论文用 64 核） |
| RNAinverse-pf | 进程内直接调 `RNA.inverse_pf_fold`，驱动在 `harness/run_rnainverse.py: solve_one_bounded(target, B, "pf", seed, init="random", timeout)` | 起始序列随机 |

---

## §2 Rfam-Taneda 到底 29 题还是 27 题 —— 我们定不了，要你定

Phase 0 只跑了 Eterna100-V2，**Taneda 一次都没跑过**，所以我们手上没有能判这件事的数据。

能提供的只有方法论：Eterna100 的 V1/V2 我们做过交叉审计（`data/eterna100/source_audit.json`），
把四个上游仓库各自带的拷贝逐题比对，结果是 V1/V2 各 100 题完全一致，而 SAMFEO 自带的
`eterna100.txt` 按内容比对只和 V2 对上 81 题 → 它其实是 V1。Taneda 可以照同样的办法做：
把 rnainvbench（29）和 RNA-Design-LM（27）各自的拷贝逐题比对，看差的 2 题是被删了还是被合并了。
**但这需要你先说以哪个为准**，否则两套题号不通用，表格没法横向比。

---

## §4 一处需要更正：Phase 0 的横轴不是整体标错，是**分方法**对错不一

你 §4 写「那些曲线的横轴标签是错的（标着折叠数，量的是时间）」——这个判断对 5 个方法里的 3 个成立，
对另外 2 个不成立。精确情况是（README §5.1 的「计数方式」列）：

| 方法 | 折叠数怎么来的 | 横轴是否可信 |
|---|---|---|
| NEMO | C++ 里 `omp atomic` 计数器，**精确** | ✅ 可信 |
| SAMFEO | Python monkeypatch 包住 ViennaRNA，**精确**（见 `harness/foldcount.py`） | ✅ 可信 |
| RNAinverse-pf | monkeypatch 能数到 `inverse_pf_fold` 的调用，但**它在 C 内部自己折的那些数不到** → 半估计 | ⚠️ 下界 |
| DesiRNA | `wall ÷ 标定的单次折叠耗时`，**估计** | ❌ 你说得对 |
| SamplingDesign | 同上，**估计** | ❌ 你说得对 |

也就是说正式跑只要把 DesiRNA 和 SamplingDesign 换成真计数，整条折叠轴就都是硬数了。
`harness/foldcount.py` 已经按你 §1 要的口径**分类型**计数（`mfe` / `pf` / `subopt`，另外单独记
`eval` / `pr` / `ned` / `sample` / `inverse`），并且带 `by_length` 直方图，正好够你做单次折叠成本标定。

### 一个现在就能看出来的东西：SAMFEO 的预算几乎全花在 pf 上

Phase 0 落盘的 229 个 SAMFEO 计数文件（`results/solvedB/samfeo_v2_B100000/_work_*/samfeo_counts_*.json`，
因为体积没进这个仓库，但格式如下）里，单题典型值是：

```json
{"counts": {"mfe": 1, "pf": 9674, "pr": 9674},
 "by_length": {"mfe:L26": 1, "pf:L26": 9674, "pr:L26": 9674}}
```

→ SAMFEO 每题只折 1 次 MFE，其余近万次全是配分函数 + 碱基对概率。
把 mfe 和 pf 混成一个「折叠调用数」会严重低估它的真实成本，**你 §1 要分三类报是对的**。

---

## §5.1 截尾不对称：现状是「已定位、未修」

你表格里的比例和我们测的一致（那四行就是从 `harness/censoring_audit.py` 出来的）。补充两点：

- **NEMO 的 0% 不是因为它更强，是因为它原版就在退出前打印 `closest_seq`**。我们没为它做任何特殊处理。
- 另外四个是被外层 `subprocess` 杀掉、stdout 为空。所以**它们的 Phase 0 数字全是下界**；
  SAMFEO 和 SamplingDesign 更糟——它们连名义上的 10⁵ 折叠预算都没领到就被墙钟掐了。

补丁还没做。插入点在 `harness/run_campaign.py` 每个方法各自的 `run_*()` 里：
现在是 `subprocess.run(..., timeout=...)` 一刀切，要改成「捕获 `TimeoutExpired` → 从上游的
中间输出里取当前最好序列」。四个方法各自的「当前最好解」落在哪不一样（SamplingDesign 打
`Best Design:` 到 stdout，SAMFEO/DesiRNA 写工作目录下的结果文件），所以是四个独立的小补丁，
不是一个通用改法。

---

## §6 并行度：Phase 0 实际给了多少

全部 5 个方法都是 `--cpus-per-task=1`、`--mem=2G`（`slurm/42_campaign_v2.sbatch`）。
所以你 §6 建议的配置里，**SamplingDesign（要 32–64 核）和 DesiRNA（要 10 核）这两条 Phase 0 都没满足**。
NEMO 的 `OMP_NUM_THREADS=1` 是满足的，而且是我们实测后主动钉死的（同题 1 线程折 21 次 / 8 线程折 60 次）。

内存实测峰值 3–82 MB/进程，所以 2 G 是极宽松的；给 SamplingDesign 加到 64 核时内存不用动。

---

## ❗ 一个会影响你 §2「seed 数 8」的问题：NEMO 没有 seed 开关

`NEMO` 的二进制**不接受 `--seed`**，内部用 `int_urn` 自取随机数，我们无法从外部设定
（`harness/run_campaign.py:56-58` 有注释和 `seed_note` 字段如实记了这件事）。

后果：Phase 0 里 NEMO 的「5 个 seed」实际是**5 次不受控的独立运行**，不是 5 个可复现的种子。
它的跨 seed 标准差（±0.8 题）量的是进程间随机性，复现不了同一条轨迹。
你要 8 seeds 的话，对 NEMO 只能有两个选择：
(a) 接受「8 次独立运行」这个口径并在表里标注；或者
(b) 再给上游打一个 `srand` 补丁。(b) 我们能做，但会改动上游行为，要你点头。

---

## §8 按你的优先级，现在的状态

| # | 你写的 | 状态 |
|---|---|---|
| 1 | 确认 DesiRNA 命令行 | ✅ **本文件上面已答完**，不花机时。结论：Turner 1999 排除；真凶是 `-r` 默认 10 + 10 replica 挤 1 核 + `+120 s` 泄漏 |
| 2 | 四个方法打 checkpoint 补丁 | ⬜ 未做，插入点已定位（§5.1） |
| 3 | 控制改折叠/步数驱动 + 配并行度 | ⬜ 未做。SamplingDesign 的 `--step 2000` 写死那条要一起改 |
| 4 | 补 RNA-Design-LM | ⬜ 未跑。**卡在缺东西**：它需要 `rnad/` 下那 10 个脚本，我们手上没有；另外 Rfam-Learn-Train 65k 的 pickle 也缺，要你给或给授权 |
| 5 | 跑完整 campaign | ⬜ 等 1–4。按 Phase 0 实测折算，你 §2 那张表（3208 次运行/方法 × 6 方法）约 **2500 核时**，和你的估计一致 |

### 开跑之前还需要你定的三件事

1. **Taneda 用 29 还是 27**（§2）——不定的话题号不通用。
2. **NEMO 的 seed**：接受「8 次独立运行」，还是允许我们打 `srand` 补丁（上面那节）。
3. **要不要保留 SAMFEO 和 SamplingDesign**：Phase 0 里这两个**独占题 0 道**（任何它们解出的题，
   至少有另一个方法也解出了），但吃掉了 325 核时里的 200。按你的新规格给 SamplingDesign 64 核之后
   成本还会涨。它们当对照组有价值，但如果机时紧，这是第一个可以砍的地方——这个取舍要你拍。
