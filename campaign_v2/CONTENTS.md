# 这个目录里有什么（Baseline Campaign v2）

对应 `campaign_spec.md` v2 的交付。先读 `HANDOVER.md` —— 它列出跑完了什么、
哪些地方与 spec 有出入、哪些要你定。

## 文档

| 文件 | 内容 |
|---|---|
| **`HANDOVER.md`** | **先读这个。** 交付说明：6/9 行方法、七项与 spec 的出入、要你定的 6 件事、资源需求 |
| `TABLE_v2.md` | spec §1 的表（完整版）：两套判据、分类型折叠调用数、预算实现度、第二条预算轴、严格截断、数据完整性 |
| `LM_CURVE.md` | RNA-Design-LM 的 solved@N 曲线（spec §4），含预算不一致的标注与饱和判断 |
| `SAMFEO_UPSTREAM_CRASH.md` | SAMFEO 的 softmax 溢出：复现方法、为什么原来那次跑没暴露它、对数字的影响（无） |
| `CUDNN_SDPA_CONTROL.md` | cuDNN fused SDPA 开关的对照实验，以及我们在这件事上犯过的一个测量错误 |
| `ANSWERS_campaign_spec_v2.md` | 2026-11-25 写的、**跑之前**对你 spec 的逐条答复（命令行、Rfam-Taneda 29/27、NEMO 没有 seed 开关等）。保留为历史：其中几条现在已由结果回答，以 `HANDOVER.md` 为准 |
| `campaign_spec_as_received.md` | 我们收到的那份 spec 原文，便于对位 |

## 代码与数据

| 目录 | 内容 |
|---|---|
| `harness/` | 评测 harness。入口：`run_campaign_v2.py`（跑）、`verify.py`（统一重验证）、`audit_results.py`（体检）、`table_v2.py`（出表）、`lm_select.py` / `lm_curve.py` / `lm_curve_table.py`（LM 的后处理） |
| `env/` | 环境搭建：`clone_all.sh`、`create_envs.sh`、`patch_nemo.py`（给 NEMO 打预算闸和折叠计数器） |
| `slurm/` | 作业脚本，文件名前缀即执行顺序 |
| `data/` | 基准集（Eterna100-V1/V2、Rfam-Taneda、ArchiveII、DesiRNA 公布序列、Koodli 序列） |
| `results/campaignV2/` | 逐题逐 seed 的原始行（带 `stop_reason` / `rc` / `fold_budget_used`）、统一重验证产物、环境留痕 |

## 怎么复核

```bash
python -I harness/audit_results.py          # 体检，退出码 0 = 过
python -I harness/table_v2.py --out TABLE_v2.md
python -I harness/lm_curve_table.py
```

体检会把三类问题分开报：**进退出码的问题**、**被 `_fix` 取代的格子**（留作证据，
不计入退出码）、**已归档的上游缺陷**（钉死到单行，见 `SAMFEO_UPSTREAM_CRASH.md`）。

## 刻意没进包的东西

| 没进包 | 为什么 |
|---|---|
| `results/campaignV2/lm/*_decode.jsonl`（7.9 G） | LM 的解码中间产物。从 select 之后的产物就能复核全部数字，没必要传 |
| `third_party/`（上游克隆）、`models/`、`build/` | 用 `env/clone_all.sh` 和 `env/create_envs.sh` 在你那边重建 |
| `logs/`、`_work_*/` | 作业日志与上游工具的中间产物 |
| LM 的解码路径（`harness/run_lm.py`、`slurm/52_lm_run`、`54_lm_decode_shard`） | 依赖我们这边的私有配置。**LM 的后处理（select / verify / curve）照常进包**，所以表里 LM 那一行的数你可以从 select 产物完整复核 |

## 口径上最容易读错的三处

1. **预算不是处处一致**：RNA-Design-LM 在 Eterna100-V1 / Rfam-Taneda / ArchiveII 上
   只跑了 B=1,000，是名义值的 1/10。表里的格子会自己打 🚨，`HANDOVER.md` §2.1 给了
   「补预算值多少」的上界。
2. **曲线末端是并集，表里的格子不是**。两者只在 N = 单 seed 预算处可比。
3. **DesiRNA 的折叠调用数是空的，不是 0**。它的计数器只反映进程数，
   填一个会被当成真数读的值比留空更坏，证据见 `TABLE_v2.md` 的 † 脚注。
