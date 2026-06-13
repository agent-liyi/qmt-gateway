## 1. 实时 K 线合成

本文档解释从 xtquant 订阅的全推数据，如何合成为1m, 30m 和 日线的算法。具体实现是 [qmt_gateway/services/quote_service.py](../qmt_gateway/services/quote_service.py) 中 `_update_bar` 的合成逻辑

### 1.1. 背景：xtquant tick 字段语义

xtquant 在 `subscribe_whole_quote` / `subscribe_quote` / `get_full_tick` / `get_market_data_ex` 等所有公开行情接口中保持同一套字段语义：

| 字段                    | 含义                     |
| ----------------------- | ------------------------ |
| `lastPrice`             | 最新价                   |
| `open` / `high` / `low` | 当日开盘以来极值         |
| `volume`                | **当日累计成交量（股）** |
| `amount`                | **当日累计成交额（元）** |
| `openInt`               | 累计持仓量（期货）       |

也就是说 `tick.volume` / `tick.amount` 表达的是"截至本次 tick 那一刻，**自开盘以来**的总成交"，不是本 tick 的 delta。

### 1.2. k 线的索引

A 股标准分钟 K 线的语义：**bar.time = 区间右端点（结束时刻）**。聚宽、Tushare、xtquant 自带的历史 K 线、通达信、Wind 全部按此对齐。

- 09:30:00 ~ 09:30:59 的成交属于 **09:31** bar
- 09:31:00 ~ 09:31:59 的成交属于 **09:32** bar
- 一直到 14:59:00 ~ 14:59:59 → **15:00** bar（当日最后一根）

分钟线以 **09:31** 为第一根 bar；它的开盘价等于集合竞价的开盘价，收盘价为截止到09:31（不含）的最后一个 tick 的 lastPrice，成交量为最后一个 tick 的 volume，因此它包含了集合竞价。

30分钟线以 **10:00** 为第一根 bar（覆盖 09:30 ~ 10:00 这 30 分钟）；其它同 1m。

实现层面：日内级别用 `bar_timestamp = ((ts // interval) + 1) * interval`，把"区间内任意秒"映射到该区间的右端点。日线 (`interval=86400`) 直接用 `now.replace(hour=0, minute=0, second=0)`，bar.time 取当日 0 点。

### 1.3. 发布时间和频率

xtquant 目前每3秒推送一次 tick 数据，从 09:15 开始。但我们 **不在集合竞价期间合成 K 线**——09:15 ~ 09:29:59 的 tick 进 `_on_tick` 之后会被时间闸门拦截（按 `tick.time` / server_time 判断，**不依赖本地时钟**），不进 `_update_bar`、不向 `/ws/quotes` 推送。

因此 `/ws/quotes` 的第一根 1m bar 落在 **09:30:00 第一个 tick 触发的 09:31 bar**——它会自然包含集合竞价的成交（因为 `tick.volume` 是当日累计，09:30:00 第一个 tick 的 volume 已经把集合竞价撮合量算进去了）。

集合竞价撮合行情（09:15 ~ 09:29:59）走独立 endpoint **`/ws/auction`**，**每 tick 一条**地原样转发关键字段（`symbol / price / open / high / low / volume / amount / stock_status / phase`），不做 K 线合成。客户端可在 09:25 撮合那一帧（`phase == "matching"` 且 `open != 0` 且 `volume > 0`）立刻拿到稳定开盘价，无需等到 09:30。详见 `docs/api.md` 的 `WS /ws/auction` 段、issue #81。

### 1.3.1. xtquant 全推 tick 行为速览

来自 [wiki "xtquant 全推 Tick 行为"](https://github.com/zillionare/qmt-gateway/wiki/xtquant-%E5%85%A8%E6%8E%A8-Tick-%E8%A1%8C%E4%B8%BA) 的实测结论，本服务的实现以此为准：

| 时段                 | server_time          | 字段表现                                                                         | 本服务的处理                  |
| -------------------- | -------------------- | -------------------------------------------------------------------------------- | ----------------------------- |
| 订阅瞬间             | `time = 0`（凌晨）   | `lp = open = lastClose`、`vol = 0`、`status = 0`，是订阅快照                     | 直接丢弃（`tick.time<=0` 闸门） |
| 09:15 - 09:19:59     | auction A（可撤单）  | `lp` 是虚拟撮合价；`open = high = low = 0`、`vol = 0`、`status = 2`              | `/ws/auction`，`phase=auction_a`  |
| 09:20 - 09:24:59     | auction B（不可撤单）| 同 A 段（实测仍持续推送，频率不变）                                              | `/ws/auction`，`phase=auction_b`  |
| **09:25 ± 几秒**     | ⭐ 撮合那一帧        | `open / high / low / volume` 同时首次填入，`open = high = low = lp = 撮合成交价` | `/ws/auction`，`phase=matching`   |
| 09:25 - 09:29:59     | 静默期               | OHLV 锁定不变；仅 `lp` 偶动；`status = 3`                                        | `/ws/auction`，`phase=matching`   |
| 09:30 - 11:30        | 连续竞价             | `open` 恒定；`high / low` 单调扩张（不等于 `max/min(lp)`）；`vol` 累计           | `/ws/quotes`（K 线合成）          |
| 11:30 ± 6s           | 早盘收盘 tick        | 各标的推 1 条带 `status = 4` 的封盘 tick                                         | 同连续竞价                    |
| 11:30 - 12:45        | 午休                 | xtquant 不推送                                                                   | —                             |

**额外约束**：

- 撮合时刻准确性：深交所个股 09:25:00 准时；上交所个股 09:25:02-03；指数最迟 09:25:09。客户端等"撮合那一帧"时不要依赖整点。
- `tick.high / tick.low` 是**当日实际成交**的累计极值（含 09:25 撮合价，**不含集合竞价过程中未成交的虚拟撮合价**）；上层不要从 `lp` 重算 high/low，直接用字段。
- `volume / amount` 是当日累计；用 `max(...)` 即拿到当日终值。

### 1.4. 成交量计算

由于tick携带的是当日累计成交量/成交额，因此在合成1m, 3m 分钟时，需要对 bar 内的实际成交量另行计算。

我们把"上一根 bar 区间内的最后一个 tick.volume"——记作 `ref_volume`。于是在每一个 tick 到达时，用当前 tick.volume - ref_volume 就是本 bar 到现在 tick 为止的成交量。

这里的关键是 ref_volume 的更新：

```
1) ref_volume 初始化值都为零
2) 在新的 tick 到来时，如果 tick 的时间跨越了 bar的时间边界，更新 ref_volume <- last_tick.volume
3) 如果 tick 的时间未跨越，则保持不变。
```

下面用 4 个 tick 把状态走一遍（注意 bar 索引为区间右端点，09:30:xx 的 tick 落在 09:31 bar）。xtquant 推过来的 `tick.volume` 是当日累计（从 0 起算）。

| 步骤  | 时刻     | tick.volume | bar索引 | ref_vol | volume  | comments    |
| ----- | -------- | ----------- | ------- | ------- | ------- | ----------- |
| tick1 | 09:30:30 | 100000      | 09:31   | 0       | 100000  | 不变        |
| tick2 | 09:30:55 | 100300      | 09:31   | 0       | 100300  | 不变        |
| tick3 | 09:31:02 | 100500      | 09:32   | 100300  | **200** | 跨 bar 更新 |
| tick4 | 09:31:30 | 100800      | 09:32   | 100300  | **500** | 不变        |

bar.time 序列 = `[09:31, 09:31, 09:32, 09:32]`——**一根 bar 会被推送多次**，每次都按"现在掌握的最后一个 tick"刷新 volume。

最终 4 次推送的 bar.volume = `[100000, 100300, 200, 500]`。

对于日线，由于不存在跨 bar 的情况，所以，成交量就始终等于 tick.volume。



## 2. 引用

- 历史 issue：[#73](https://github.com/zillionare/qmt-gateway/issues/73)、[#74](https://github.com/zillionare/qmt-gateway/issues/74)、[#80](https://github.com/zillionare/qmt-gateway/issues/80)（bar 时间索引 + 集合竞价不合成）、[#81](https://github.com/zillionare/qmt-gateway/issues/81)（`/ws/auction` 集合竞价独立 endpoint）
- 修复 PR：[#75](https://github.com/zillionare/qmt-gateway/pull/75)
- 实测背景：[wiki "xtquant 全推 Tick 行为"](https://github.com/zillionare/qmt-gateway/wiki/xtquant-%E5%85%A8%E6%8E%A8-Tick-%E8%A1%8C%E4%B8%BA)（2026-06-12 早盘 12 标的 / 29,566 tick 实测）
