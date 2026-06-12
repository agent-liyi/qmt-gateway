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

xtquant 目前每3秒推送一次 tick 数据，从 09:15 开始。但我们 **不在集合竞价期间合成 K 线**——09:15 ~ 09:29:59 的 tick 进 `_on_tick` 之后会被时间闸门 `now.time() < 09:30` 直接 return，不进 `_update_bar`、不向 `/ws/quotes` 推送。

因此 `/ws/quotes` 的第一根 1m bar 落在 **09:30:00 第一个 tick 触发的 09:31 bar**——它会自然包含集合竞价的成交（因为 `tick.volume` 是当日累计，09:30:00 第一个 tick 的 volume 已经把集合竞价撮合量算进去了）。

集合竞价撮合行情（09:20 ~ 09:25）走独立 endpoint **`/ws/auction`**，只发 `symbol → {price, volume, amount}` 快照字典，不做 K 线合成（参考聚宽 `get_call_auction` / Tushare `acl()` 的处理方式）。详见 issue #81。

在 09:25 ~ 09:30 之间以及午盘停牌期间，xtquant 不发布行情数据。


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
