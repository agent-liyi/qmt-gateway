# 实时 K 线合成（QuoteService._update_bar）

本文档解释 [qmt_gateway/services/quote_service.py](../qmt_gateway/services/quote_service.py) 中 `_update_bar` 的合成逻辑，重点是 `volume` / `amount` 字段的"末 tick 锁定"状态机。

## 背景：xtquant tick 字段语义

xtquant 在 `subscribe_whole_quote` / `subscribe_quote` / `get_full_tick` / `get_market_data_ex` 等所有公开行情接口中保持同一套字段语义：

| 字段 | 含义 |
|---|---|
| `lastPrice` | 最新价 |
| `open` / `high` / `low` | 当日开盘以来极值 |
| `volume` | **当日累计成交量（股）** |
| `amount` | **当日累计成交额（元）** |
| `openInt` | 累计持仓量（期货） |

也就是说 `tick.volume` / `tick.amount` 表达的是"截至本次 tick 那一刻，**自开盘以来**的总成交"，不是本 tick 的 delta。

## 三种 K 线级别的不同语义

| 级别 | volume / amount 公式 | 原因 |
|---|---|---|
| 1d | `bar.volume = tick.volume`（覆盖）| 1d 整日 = 自开盘起累计，覆盖成立 |
| 1m | `bar.volume = tick.volume − ref_volume` | 日内级别需要算"本 bar 内的成交" |
| 30m | 同 1m | 同上 |

> 其它日内级别（1h / 4h / 自定义）走同一逻辑：ref 减法。

## 状态机：末 tick 锁定

日内级别的关键是"上一根 bar 区间内的最后一个 tick.volume"——记作 `ref_volume`。它的更新规则是：

```
每个 tick 到达时（不论是否跨 bar）：
  1) ref_volume ← 上一根 bar 区间内的最后一个 tick.volume
  2) bar.volume = tick.volume − ref_volume
  3) ref_volume ← tick.volume   // 立刻更新
```

关键：**`ref_volume` 在每个 tick 都更新为本 tick.volume**。因此旧 bar 的"区间内最后 tick"始终是已知的最近一个 tick，跨 bar 那一刻就能立刻算出新 bar 的第一笔 delta——**无延迟**。

## 走一遍示例

下面用 4 个 tick 把状态走一遍。xtquant 推过来的 `tick.volume` 是当日累计（从 0 起算）。

| 步骤 | 时刻 | tick.volume | 落到的 bar | ref_volume（更新前）| bar.volume = tick − ref | 新 ref_volume |
|---|---|---|---|---|---|---|
| tick1 | 09:30:30 | 100000 | 09:31 | 0 | 100000 | 100000 |
| tick2 | 09:30:55 | 100300 | 09:31 | 100000 | **300** | 100300 |
| tick3 | 09:31:02 | 100500 | 09:32 | 100300 | **200** | 100500 |
| tick4 | 09:31:30 | 100800 | 09:32 | 100500 | **300** | 100800 |

bar.time 序列 = `[09:31, 09:31, 09:32, 09:32]`——**一根 bar 会被推送多次**，每次都按"现在掌握的最后一个 tick"刷新 volume。

最终 4 次推送的 bar.volume = `[100000, 300, 200, 300]`。

注意几个要点：

- **跨 bar 那一刻（tick3）**：算的是新 bar 的"第一个 delta"。此时 ref 是上一根 bar 区间内的最后 tick.volume（tick2.volume = 100300），新 bar 的第一笔 delta = 100500 − 100300 = 200。**无延迟，不需要等下一根 bar 的 tick 来确认**。
- **同 bar 多次更新（tick2、tick4）**：每次都按"现在掌握的最后一个 tick"刷新 volume。这与 xtquant 标准 K 线（用区间内最后累计值代表该 bar）一致。
- **缺字段处理**：若 `tick.volume` 为 `None` 或 0，跳过 `ref_volume` 更新（避免把坏值灌进基线）。`bar.volume` 走 `max(0, ...)`，缺字段时保持上一笔非零值。

## 边界

- **首根 bar**：ref_volume 初始化为 0，所以首根 bar 的 `bar.volume = tick.volume - 0 = tick.volume`。**与覆盖等价**——`new_volume` 即是首根 bar 区间内最后一个 tick.volume 的合理近似。
- **跨日 / 跨时段**：当前 `_is_trade_time()` 拦截非交易时段的 tick，所以日内 bar 不会跨午休（1m）或跨日（30m）；1d 的"自开盘累计"每天日切后重置。
- **1d 的特殊性**：1d 整日 = 自开盘起累计，所以走覆盖（`bar.volume = tick.volume`），不走 ref 减法。这与 xtquant 自己导出的日 K 线一致。
- **负数保护**：`max(0, new_volume - ref_volume)` 防止 xtquant 推送异常（如累计值回落）时产生负的 volume / amount。

## 与历史下载接口的关系

[`/api/history/minutes/jobs`](api.md#历史分钟线下载) 走 xtquant 自带 K 线合成（`xtdata.subscribe_quote(..., period='1m', ...)`），量纲本来就对——**不经过本状态机**，与本文档描述的逻辑独立。

## 引用

- 代码：[qmt_gateway/services/quote_service.py:240-325](../qmt_gateway/services/quote_service.py#L240-L325)
- 历史 issue：[#73](https://github.com/zillionare/qmt-gateway/issues/73)、[#74](https://github.com/zillionare/qmt-gateway/issues/74)
- 修复 PR：[#75](https://github.com/zillionare/qmt-gateway/pull/75)
