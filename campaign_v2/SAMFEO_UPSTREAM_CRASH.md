# SAMFEO 的上游数值 bug：Boltzmann 概率溢出成 NaN

## 现象

Rfam-Taneda(29) 的 SAMFEO 格子里，464 次运行有 **2 次** 没有产出任何设计序列：

| 题 | 名称 | 长度 | seed（= `--start`） | 折叠数 | 墙钟 | rc |
|---|---|---|---|---|---|---|
| 16 | taneda29_16 | 129 | 4 | **20** / 9806 | 1.83 s | **1** |
| 23 | taneda29_23 | 451 | 12 | **24** / 9806 | 4.84 s | **1** |

同一次运行里其余 27 题都正常用掉 9806 次折叠、每题几十秒到 25 分钟。这两题是秒级退出。

## 原因（可稳定复现）

直接用官方入口重跑 `main.py --online --start 4`（题 16）和 `--start 12`（题 23），
两次都抛同一个异常：

```
third_party/samfeo/main.py:298: RuntimeWarning: overflow encountered in exp
  probs_boltzmann_1 = np.exp(score_list) / sum(np.exp(score_list))
third_party/samfeo/main.py:298: RuntimeWarning: invalid value encountered in divide

Traceback (most recent call last):
  File "third_party/samfeo/main.py", line 708, in <module>
  File "third_party/samfeo/main.py", line 323, in samfeo
    raise e
  File "third_party/samfeo/main.py", line 315, in samfeo
    p = np.random.choice(k_best, p=probs_boltzmann_1)
ValueError: probabilities contain NaN
```

`score_list` 的实测取值（题 23）：

```
[1.41, 74.6, 2532, 10463, 1.75e5, 3.70e4, 9867, 4.77e5, 6.37e4, 2.89e8]
```

`np.exp(2.89e8)` 溢出成 `inf`，分母也是 `inf`，`inf/inf = NaN`，于是
`np.random.choice(p=...)` 拒绝这个概率向量。缺的是 softmax 的标准做法 ——
先减去 `max(score_list)` 再取指数。SAMFEO 在 `main.py:323` 自己 `raise e`，
进程以 rc=1 退出。

## 为什么原来那次跑没暴露它

原始的 SAMFEO 跑没有传 `--start`。SAMFEO 没有 `--seed` 开关，它的种子是
`seed_np = 2020 + args.start * 2021`（`main.py:703`），所以 `--start` 就是官方的种子旋钮。
不传的后果是 8/16 个 seed 跑出逐字节相同的序列（实测 100/100 题相同），±std 恒为 0。
修正成传 `--start` 之后 seed 才真正生效，这个与种子相关的崩溃也就跟着露出来了。
换句话说：**崩溃不是我们引入的，是「让 seed 真正起作用」之后才看得见的 SAMFEO 固有行为。**

## 对表里数字的影响：没有

- 题 16 和题 23 在全部 16 个 seed 下 SAMFEO **一次都没解出来**（0/16），
  所以这 2 次崩溃无论算不算，这两题都是未解。
- 两行都在 verified 文件里，按未解计入。该格子 464 行一行不缺，
  所以 `pass@16` 的分母是完整的 29 题。
- 表里 SAMFEO / Rfam-Taneda(29) = **24.0 ± 0.4 (MFE) / 23.8 ± 0.4 (uMFE)** 不受影响。

## 处理方式

**不改上游代码。** baseline 必须是官方实现，给 SAMFEO 补一个 softmax 稳定化
等于替它提升性能，那样的数就不能再叫 SAMFEO 的成绩了。如实报告。

**改的是我们的 harness**，原来有两个地方会把这次崩溃藏起来：

1. `run_samfeo` 原来无条件把 `stop_reason` 写成 `steps_exhausted_or_solved` ——
   在给一次崩溃贴「正常跑完」的标签。现在 rc 非 0 时写 `upstream_crash`。
2. `run_samfeo` 用 `capture_output=True` 抓了 stderr 却丢掉不用，所以崩溃理由不可见。
   现在 rc 非 0 时保留 `samfeo_stderr_tail`（末 600 字节）。

已有数据不需要重跑：`rc=1` 本来就写在行里了，所以这两次崩溃从现有 jsonl 里就能筛出来
（`rc not in (0, 7, None)`），只是 `stop_reason` 的标签不对。重跑整个格子（16 seed ×
29 题 ≈ 45 核时）只为改 2 行的标签，而且数字一个都不会变，不值得。

**审计也补了两个漏**（`harness/audit_results.py`）：

- 空序列和「raw 有 verified 没有」原来只印在表里、不进「发现问题」，于是闸门会放过它们。
  这 2 行就是这样溜过去的。
- 新增 `rc≠0` 这一列并进「发现问题」。只查空序列是不够的：一个方法可以先吐出几条序列
  再崩，那样行里有序列、看起来完全正常，实际上只跑了一小部分预算，却会被当成
  「跑满预算的一次运行」—— 这种行在横向比较里是最危险的，因为它让该方法看起来
  「用更少预算拿到同样成绩」。

## 需要协作者定的事

这 2 次崩溃按未解计，是因为 SAMFEO 自己没能用掉给它的预算。另一种口径是把它们当作
缺失数据剔除（分母变 27 题）。我们选了前者并写进报告，因为剔除会让 SAMFEO 的
`pass@16` 看起来更高，而崩溃是它自己的行为，不是外部干扰。如果你认为该用后者，
说一声，表可以重出。
