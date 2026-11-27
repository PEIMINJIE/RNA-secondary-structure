# campaign_spec v2 §1 的表

每个准确率格子两行：**MFE 判据** / **uMFE 判据**，都是「跨 seed 的单次运行均值 ± 标准差」，**未取并集**。折叠调用数按题取中位数。

| 方法 | Eterna100-V2<br>pass@8 | Eterna100-V1<br>pass@8 | Rfam-Taneda(29)<br>pass@16 | ArchiveII<br>pass@1 | mfe<br>调用数 | pf<br>调用数 | subopt<br>调用数 | 计数方式 |
|---|---|---|---|---|---|---|---|---|
| NEMO | 78.0 ± 1.9<br>67.6 ± 4.0<br><sub>8 seeds × 100 题</sub> | 73.9 ± 1.0<br>64.9 ± 2.0<br><sub>8 seeds × 100 题</sub> | 23.9 ± 0.2<br>21.4 ± 1.4<br><sub>16 seeds × 29 题</sub> | 971.0 ± 0.0<br>865.0 ± 0.0<br><sub>1 seeds × 1144 题</sub> | 65 | 0 | 0 | 精确（C++ 计数器） |
| DesiRNA | 87.4 ± 1.2<br>84.9 ± 1.4<br><sub>8 seeds × 100 题</sub> | 76.9 ± 0.8<br>74.1 ± 1.0<br><sub>8 seeds × 100 题</sub> | 24.6 ± 0.5<br>24.4 ± 0.6<br><sub>16 seeds × 29 题</sub> | 978.0 ± 0.0<br>957.0 ± 0.0<br><sub>1 seeds × 1144 题</sub> | 测不到<sup>†</sup> | 测不到<sup>†</sup> | 测不到<sup>†</sup> | **不可用**（monkeypatch 只抓到每进程固定 ~132 次初始化折叠）<sup>†</sup> |
| RNAinverse-pf | 76.2 ± 2.1<br>74.2 ± 1.4<br><sub>8 seeds × 100 题</sub> | 72.0 ± 1.2<br>70.5 ± 1.1<br><sub>8 seeds × 100 题</sub> | 23.4 ± 0.6<br>23.1 ± 0.7<br><sub>16 seeds × 29 题</sub> | 948.0 ± 0.0<br>928.0 ± 0.0<br><sub>1 seeds × 1144 题</sub> | 不可分解 | 不可分解 | 不可分解 | mfe 等效（墙钟÷单次mfe标定，与可见计数取 max；C 内部折叠不可见） |
| SAMFEO | 77.9 ± 2.0<br>73.6 ± 1.6<br><sub>8 seeds × 100 题</sub> | 73.6 ± 2.1<br>69.9 ± 2.0<br><sub>8 seeds × 100 题</sub> | 24.0 ± 0.4<br>23.8 ± 0.4<br><sub>16 seeds × 29 题</sub> | 958.0 ± 0.0<br>941.0 ± 0.0<br><sub>1 seeds × 1144 题</sub> | 2 | 9,804 | 0 | 精确（monkeypatch） |
| SamplingDesign | 45.1 ± 2.1<br>43.4 ± 2.2<br><sub>8 seeds × 100 题</sub> | 44.6 ± 1.9<br>43.2 ± 2.1<br><sub>8 seeds × 100 题</sub> | 17.6 ± 0.7<br>17.1 ± 1.0<br><sub>16 seeds × 29 题</sub> | 779.0 ± 0.0<br>761.0 ± 0.0<br><sub>1 seeds × 1144 题</sub> | 0 | 10,000 | 0 | 结构性（步数×样本数，C++ 未插桩） |
| RNA-Design-LM (SL+RL) | 80.5 ± 1.1<br>77.2 ± 0.9<br><sub>8 seeds × 100 题</sub> | 70.1 ± 0.6<br>67.9 ± 1.4<br><sub>8 seeds × 100 题</sub><br>🚨 B=1,000<br>（名义 10,000） | 24.0 ± 0.0<br>23.8 ± 0.4<br><sub>16 seeds × 29 题</sub><br>🚨 B=1,000<br>（名义 10,000） | 966.0 ± 0.0<br>952.0 ± 0.0<br><sub>1 seeds × 1144 题</sub><br>🚨 B=1,000<br>（名义 10,000） | 1 | 0 | 0 | 精确（best-of-N 选择） |

🚨 **预算不一致：下列格子不是在名义预算 B = 10,000 次折叠调用上跑的**，横向比较时必须把这件事一起说出去。

| 方法 | benchmark | 实际 B | 相对名义 |
|---|---|---|---|
| RNA-Design-LM (SL+RL) | Eterna100-V1 | 1,000 | 1/10 |
| RNA-Design-LM (SL+RL) | Rfam-Taneda(29) | 1,000 | 1/10 |
| RNA-Design-LM (SL+RL) | ArchiveII | 1,000 | 1/10 |

预算小于名义值**对该方法不利**，所以这不是在给它加分；但不标出来，读表的人会把它当成同预算的成绩。补预算值多少，见 `reports/lm_curve_table.md` 的「饱和行为」一节 —— 那里用并集轴给出了上界。

<sup>†</sup> **DesiRNA 的折叠计数器测不到它的折叠量**，所以这些格子宁可留空也不填一个会被当成真数读的数。实测证据（3,208 次干净运行）：

- `折叠数 = 进程数 × 132.2`，折叠/进程的标准差只有 2.1，相关系数 r = +1.000 ——变的是**进程数**，不是折叠数。
- 2,471/3,208 次运行（77%）的取值**恰好**是 13,480。这批里命中步最大的是第 10 个 RE 步 ——也就是说在 0 到那一步之间，计数器完全没有分辨率（16 nt 的 Simple Hairpin 7 秒解出，报的也是 13,480）。
- 与墙钟的相关系数 +0.52 全部由进程数中介（进程数 vs 墙钟同为 +0.518）。
- 机制：monkeypatch 只抓到了每个进程固定的那段初始化折叠，真正的搜索折叠发生在它看不到的地方。

因此 DesiRNA 的预算只能这样说：**声明的 RE 步数 `-s 110`** （加下面「步数轴」那张表给出的命中位置），绝对工作量看 「第二条预算轴」里的 CPU 折算列。⚠️ 早期报出的「折叠/步 ≈ 91.1」「超预算 14.75 倍」都是这个计数器的产物，已作废。

## 实现预算 / 名义预算（横向可比性的前提）

| 方法 | benchmark | 中位 | p90 | 最大 | >1.1× 比例 | 可用严格截断修正 |
|---|---|---|---|---|---|---|
| NEMO | Eterna100-V2 | 0.04 | 1.00 | 1.02 | 0% | 是 |
| NEMO | Eterna100-V1 | 0.04 | 1.00 | 1.02 | 0% | 是 |
| NEMO | Rfam-Taneda(29) | 0.00 | 1.00 | 1.15 | 0% | 是 |
| NEMO | ArchiveII | 0.00 | 1.00 | 1.01 | 0% | 是 |
| DesiRNA | （全部） | 测不到<sup>†</sup> | 测不到<sup>†</sup> | 测不到<sup>†</sup> | 测不到<sup>†</sup> | 折叠轴上不行；步数轴上可以（轨迹给出首次命中 RE 步）|
| RNAinverse-pf | Eterna100-V2 | 0.40 | 1.48 | 3.24 | 25% | 是 |
| RNAinverse-pf | Eterna100-V1 | 0.43 | 1.51 | 3.53 | 24% | 是 |
| RNAinverse-pf | Rfam-Taneda(29) | 0.39 | 1.21 | 2.31 | 14% | 是 |
| RNAinverse-pf | ArchiveII | 0.27 | 1.10 | 1.44 | 10% | 是 |
| SAMFEO | Eterna100-V2 | 0.98 | 0.98 | 0.98 | 0% | 否（记的是总数，非命中时计数） |
| SAMFEO | Eterna100-V1 | 0.98 | 0.98 | 0.98 | 0% | 否（记的是总数，非命中时计数） |
| SAMFEO | Rfam-Taneda(29) | 0.98 | 0.98 | 0.98 | 0% | 否（记的是总数，非命中时计数） |
| SAMFEO | ArchiveII | 0.98 | 0.98 | 0.98 | 0% | 否（记的是总数，非命中时计数） |
| SamplingDesign | Eterna100-V2 | 1.00 | 1.00 | 1.00 | 0% | 否（记的是总数，非命中时计数） |
| SamplingDesign | Eterna100-V1 | 1.00 | 1.00 | 1.00 | 0% | 否（记的是总数，非命中时计数） |
| SamplingDesign | Rfam-Taneda(29) | 1.00 | 1.00 | 1.00 | 0% | 否（记的是总数，非命中时计数） |
| SamplingDesign | ArchiveII | 1.00 | 1.00 | 1.00 | 0% | 否（记的是总数，非命中时计数） |
| RNA-Design-LM (SL+RL) | Eterna100-V2 | 0.00 | 1.00 | 1.00 | 0% | 否（记的是总数，非命中时计数） |
| RNA-Design-LM (SL+RL) | Eterna100-V1 | 0.00 | 1.00 | 1.00 | 0% | 否（记的是总数，非命中时计数） |
| RNA-Design-LM (SL+RL) | Rfam-Taneda(29) | 0.00 | 1.00 | 1.00 | 0% | 否（记的是总数，非命中时计数） |
| RNA-Design-LM (SL+RL) | ArchiveII | 0.00 | 1.00 | 1.00 | 0% | 否（记的是总数，非命中时计数） |

## 第二条预算轴：mfe 等效工作量

| 方法 | benchmark | (a) 计数折算 | (b) CPU 折算 | b/a | 实现/名义 (按 b) |
|---|---|---|---|---|---|
| NEMO | Eterna100-V2 | 370 | 132 | 0.39 | 0.01× |
| NEMO | Eterna100-V1 | 376 | 154 | 0.38 | 0.02× |
| NEMO | Rfam-Taneda(29) | 19 | 5 | 0.32 | 0.00× |
| NEMO | ArchiveII | 23 | 9 | 0.37 | 0.00× |
| DesiRNA | Eterna100-V2 | 测不到 | 31,817 | — | 3.18× |
| DesiRNA | Eterna100-V1 | 测不到 | 38,126 | — | 3.81× |
| DesiRNA | Rfam-Taneda(29) | 测不到 | 21,872 | — | 2.19× |
| DesiRNA | ArchiveII | 测不到 | 25,108 | — | 2.51× |
| RNAinverse-pf | Eterna100-V2 | 测不到 | 3,913 | — | 0.39× |
| RNAinverse-pf | Eterna100-V1 | 测不到 | 4,227 | — | 0.42× |
| RNAinverse-pf | Rfam-Taneda(29) | 测不到 | 3,850 | — | 0.39× |
| RNAinverse-pf | ArchiveII | 测不到 | 2,663 | — | 0.27× |
| SAMFEO | Eterna100-V2 | 17,090 | 9,360 | 0.54 | 0.94× |
| SAMFEO | Eterna100-V1 | 17,090 | 10,168 | 0.57 | 1.02× |
| SAMFEO | Rfam-Taneda(29) | 17,061 | 7,388 | 0.46 | 0.74× |
| SAMFEO | ArchiveII | 17,090 | 8,767 | 0.52 | 0.88× |
| SamplingDesign | Eterna100-V2 | 17,430 | 14,517 | 0.80 | 1.45× |
| SamplingDesign | Eterna100-V1 | 17,430 | 14,290 | 0.79 | 1.43× |
| SamplingDesign | Rfam-Taneda(29) | 17,430 | 11,591 | 0.65 | 1.16× |
| SamplingDesign | ArchiveII | 17,430 | 12,294 | 0.72 | 1.23× |

### 严格截断后的 MFE 命中（超预算才命中的一律作废）

| 方法 | benchmark | 原始 | 严格截断 | 差 |
|---|---|---|---|---|
| NEMO | Eterna100-V2 | 624 | 624 | +0 |
| NEMO | Eterna100-V1 | 591 | 591 | +0 |
| NEMO | Rfam-Taneda(29) | 383 | 383 | +0 |
| NEMO | ArchiveII | 971 | 971 | +0 |
| DesiRNA | Eterna100-V2 | 699 | 不可判 | — |
| DesiRNA | Eterna100-V1 | 615 | 不可判 | — |
| DesiRNA | Rfam-Taneda(29) | 393 | 不可判 | — |
| DesiRNA | ArchiveII | 978 | 不可判 | — |
| RNAinverse-pf | Eterna100-V2 | 610 | 528 | -82 |
| RNAinverse-pf | Eterna100-V1 | 576 | 499 | -77 |
| RNAinverse-pf | Rfam-Taneda(29) | 374 | 358 | -16 |
| RNAinverse-pf | ArchiveII | 948 | 938 | -10 |
| SAMFEO | Eterna100-V2 | 623 | 不可判 | — |
| SAMFEO | Eterna100-V1 | 589 | 不可判 | — |
| SAMFEO | Rfam-Taneda(29) | 384 | 不可判 | — |
| SAMFEO | ArchiveII | 958 | 不可判 | — |
| SamplingDesign | Eterna100-V2 | 361 | 不可判 | — |
| SamplingDesign | Eterna100-V1 | 357 | 不可判 | — |
| SamplingDesign | Rfam-Taneda(29) | 281 | 不可判 | — |
| SamplingDesign | ArchiveII | 779 | 不可判 | — |
| RNA-Design-LM (SL+RL) | Eterna100-V2 | 644 | 不可判 | — |
| RNA-Design-LM (SL+RL) | Eterna100-V1 | 561 | 不可判 | — |
| RNA-Design-LM (SL+RL) | Rfam-Taneda(29) | 384 | 不可判 | — |
| RNA-Design-LM (SL+RL) | ArchiveII | 966 | 不可判 | — |

### 步数轴：DesiRNA 命中时用掉的步数预算比例

折叠轴对 DesiRNA 不可用<sup>†</sup>，但轨迹文件给出命中发生在第几个 RE 步，所以「命中用掉了多少预算」这句话仍然可以如实说。

| benchmark | 命中数 | 命中步/步数预算 中位 | p90 | 最大 | 首步即命中 |
|---|---|---|---|---|---|
| Eterna100-V2 | 699 | 0.009 | 0.136 | 0.909 | 33% |
| Eterna100-V1 | 608 | 0.009 | 0.027 | 0.873 | 38% |
| Rfam-Taneda(29) | 392 | 0.000 | 0.009 | 0.782 | 56% |
| ArchiveII | 978 | 0.009 | 0.009 | 0.591 | 36% |

## 墙钟保险丝触发率（spec §4 要求为 0）

| 方法 | benchmark | 运行数 | 保险丝响 | 比例 |
|---|---|---|---|---|
| NEMO | Eterna100-V2 | 800 | 0 | 0.0% |
| NEMO | Eterna100-V1 | 800 | 0 | 0.0% |
| NEMO | Rfam-Taneda(29) | 464 | 0 | 0.0% |
| NEMO | ArchiveII | 1144 | 0 | 0.0% |
| DesiRNA | Eterna100-V2 | 800 | 0 | 0.0% |
| DesiRNA | Eterna100-V1 | 800 | 0 | 0.0% |
| DesiRNA | Rfam-Taneda(29) | 464 | 0 | 0.0% |
| DesiRNA | ArchiveII | 1144 | 0 | 0.0% |
| RNAinverse-pf | Eterna100-V2 | 800 | 0 | 0.0% |
| RNAinverse-pf | Eterna100-V1 | 800 | 0 | 0.0% |
| RNAinverse-pf | Rfam-Taneda(29) | 464 | 0 | 0.0% |
| RNAinverse-pf | ArchiveII | 1144 | 0 | 0.0% |
| SAMFEO | Eterna100-V2 | 800 | 0 | 0.0% |
| SAMFEO | Eterna100-V1 | 800 | 0 | 0.0% |
| SAMFEO | Rfam-Taneda(29) | 464 | 0 | 0.0% |
| SAMFEO | ArchiveII | 1144 | 0 | 0.0% |
| SamplingDesign | Eterna100-V2 | 800 | 0 | 0.0% |
| SamplingDesign | Eterna100-V1 | 800 | 0 | 0.0% |
| SamplingDesign | Rfam-Taneda(29) | 464 | 0 | 0.0% |
| SamplingDesign | ArchiveII | 1144 | 0 | 0.0% |
| RNA-Design-LM (SL+RL) | Eterna100-V2 | 800 | 0 | 0.0% |
| RNA-Design-LM (SL+RL) | Eterna100-V1 | 800 | 0 | 0.0% |
| RNA-Design-LM (SL+RL) | Rfam-Taneda(29) | 464 | 0 | 0.0% |
| RNA-Design-LM (SL+RL) | ArchiveII | 1144 | 0 | 0.0% |

## 每次运行的墙钟中位数（仅供参考，不是主指标）

| 方法 | benchmark | 核 | 墙钟中位 | 折叠中位 |
|---|---|---|---|---|
| NEMO | Eterna100-V2 | 1 | 1.1 s | 370 |
| NEMO | Eterna100-V1 | 1 | 1.4 s | 376 |
| NEMO | Rfam-Taneda(29) | 1 | 0.1 s | 19 |
| NEMO | ArchiveII | 1 | 0.1 s | 23 |
| DesiRNA | Eterna100-V2 | 10 | 32.6 s | 测不到<sup>†</sup> |
| DesiRNA | Eterna100-V1 | 10 | 35.4 s | 测不到<sup>†</sup> |
| DesiRNA | Rfam-Taneda(29) | 10 | 59.0 s | 测不到<sup>†</sup> |
| DesiRNA | ArchiveII | 10 | 33.8 s | 测不到<sup>†</sup> |
| RNAinverse-pf | Eterna100-V2 | 1 | 31.9 s | 3,994 |
| RNAinverse-pf | Eterna100-V1 | 1 | 32.1 s | 4,316 |
| RNAinverse-pf | Rfam-Taneda(29) | 1 | 117.9 s | 3,929 |
| RNAinverse-pf | ArchiveII | 1 | 33.6 s | 2,719 |
| SAMFEO | Eterna100-V2 | 1 | 79.3 s | 9,806 |
| SAMFEO | Eterna100-V1 | 1 | 84.1 s | 9,806 |
| SAMFEO | Rfam-Taneda(29) | 1 | 135.0 s | 9,806 |
| SAMFEO | ArchiveII | 1 | 102.1 s | 9,806 |
| SamplingDesign | Eterna100-V2 | 32 | 4.0 s | 10,000 |
| SamplingDesign | Eterna100-V1 | 32 | 4.0 s | 10,000 |
| SamplingDesign | Rfam-Taneda(29) | 32 | 7.8 s | 10,000 |
| SamplingDesign | ArchiveII | 32 | 5.4 s | 10,000 |
| RNA-Design-LM (SL+RL) | Eterna100-V2 | ? | — | 2 |
| RNA-Design-LM (SL+RL) | Eterna100-V1 | ? | — | 2 |
| RNA-Design-LM (SL+RL) | Rfam-Taneda(29) | ? | — | 1 |
| RNA-Design-LM (SL+RL) | ArchiveII | ? | — | 1 |

## 数据完整性

取用目录下的产物均可完整解析，无坏行。

⚠️ 取用目录里有上游进程异常退出（`rc` 非 0）的行：

| 方法 | benchmark | rc≠0 行数 | 其中仍有序列 |
|---|---|---|---|
| SAMFEO | Rfam-Taneda(29) | 2 | 0 |

「仍有序列」那一列是 0 才算安全：非 0 意味着该次运行崩在中途、预算没跑满，但从行里看不出来。

取用的目录（有 `_fix` 的优先，旧目录保留作证据）：

- `desirna` / `archiveii` → `results/campaignV2/desirna_archiveii_B10000_fix`
- `desirna` / `taneda29` → `results/campaignV2/desirna_taneda29_B10000_fix`
- `desirna` / `v1` → `results/campaignV2/desirna_v1_B10000_fix`
- `desirna` / `v2` → `results/campaignV2/desirna_v2_B10000_fix`
- `nemo` / `archiveii` → `results/campaignV2/nemo_archiveii_B10000`
- `nemo` / `taneda29` → `results/campaignV2/nemo_taneda29_B10000`
- `nemo` / `v1` → `results/campaignV2/nemo_v1_B10000`
- `nemo` / `v2` → `results/campaignV2/nemo_v2_B10000`
- `rnainverse` / `archiveii` → `results/campaignV2/rnainverse_archiveii_B10000`
- `rnainverse` / `taneda29` → `results/campaignV2/rnainverse_taneda29_B10000`
- `rnainverse` / `v1` → `results/campaignV2/rnainverse_v1_B10000`
- `rnainverse` / `v2` → `results/campaignV2/rnainverse_v2_B10000`
- `samfeo` / `archiveii` → `results/campaignV2/samfeo_archiveii_B10000_fix`
- `samfeo` / `taneda29` → `results/campaignV2/samfeo_taneda29_B10000_fix`
- `samfeo` / `v1` → `results/campaignV2/samfeo_v1_B10000_fix`
- `samfeo` / `v2` → `results/campaignV2/samfeo_v2_B10000_fix`
- `samplingdesign` / `archiveii` → `results/campaignV2/samplingdesign_archiveii_B10000`
- `samplingdesign` / `taneda29` → `results/campaignV2/samplingdesign_taneda29_B10000`
- `samplingdesign` / `v1` → `results/campaignV2/samplingdesign_v1_B10000`
- `samplingdesign` / `v2` → `results/campaignV2/samplingdesign_v2_B10000`
