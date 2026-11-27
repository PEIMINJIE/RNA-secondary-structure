# 对照实验：cuDNN 融合注意力后端对 LM 解码的影响

## 起因

ArchiveII 的 7 个解码分片里，分片 4（作业 `52907219_4`）在跑到第 161/164 题时抛出

```
RuntimeError: Expected mha_graph.execute(handle, variant_pack, workspace_ptr.get()).is_good()
              to be true, but got false.
```

同一版本、同一镜像的其余 6 片都没事，所以这是个与张量形状相关的间歇性问题。
处理办法是在 `harness/run_lm.py` 里关掉 cuDNN 的融合 SDPA 后端
（`torch.backends.cuda.enable_cudnn_sdp(False)`），退回 flash / mem-efficient / math
后端。这三个后端与 cuDNN 融合实现数值等价，不改变采样分布。

## 对照设置

两个作业只差一个环境变量 `LM_CUDNN_SDP`，其余完全相同：同一张 B200、同一份 SL+RL
权重、ArchiveII 前 20 题 × 每题 1000 条候选、batch_size=1024、temp=2.0、带配对约束。

| 开关 | 作业 | 墙钟 | 候选 / token | 边际成本 |
|---|---|---|---|---|
| 关（现默认） | `52941692` | **76 s** | 20,000 / 758,000 | **0.1003** ms/(候选·token) |
| 开 | `52941691` | 141 s | 20,000 / 758,000 | 0.1860 ms/(候选·token) |

**关掉比开着快 1.85×。** 所以这个开关既修了崩溃，也确实提速。

逐 batch 看，差距随 prefix 长度拉大：prefix_len=42 时 2.42 s vs 3.84 s，
prefix_len=56 的末尾小 batch（544 条）是 1.82 s vs 15.51 s。与「长序列形状上走坏路径」
的解释一致，也与崩溃发生在 ArchiveII（本 campaign 里题最长的 benchmark）相符。

## 一个必须写下来的测量错误

重投的分片 4（`52912995_4`）日志里报了 `0.0039 ms/(候选·token)`，比兄弟分片快 18 倍。
**这是假的，原因是吞吐的分母用错了。** 上游 `constrained_decoding.py` 默认开
`--resume_remaining` 且以 `"a"` 模式写输出，所以重投时：

```
Resume enabled: found 160768 existing samples across 161 unique ids
ID sampling status: completed=160, partial=1, not_started=2, remaining_tasks=2232
```

本次只解码了 2,232 条，67 s 却被除在文件里的 163,000 条（含继承的 160,768 条）上。
按真实新增算，本次是 0.29 ms/(候选·token)，并不比兄弟分片快。

已修：`slurm/54_lm_decode_shard.sbatch` 现在在解码前快照输出文件的存量，吞吐只统计
本次新增；覆盖自检仍然用文件总量，因为要查的就是「这个分片最终齐不齐」。

## 对数据的影响

无。分片 4 的覆盖自检是逐题数实际条数的，通过时报
`✅ 163 题全中，每题 1000 条候选`，文件 163,000 行名副其实。

唯一需要在溯源里注明的是：该分片的候选来源是混的 —— 160,768 条产自补丁前（cuDNN 开），
2,232 条产自补丁后（cuDNN 关）。两者是同一模型、同一解码设置，后端切换数值等价，
不引入偏置。
