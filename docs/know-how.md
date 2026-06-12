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

分钟线以09:31为第一根 bar；它的开盘价等于集合竞价的开盘价，收盘价为截止到09:31（不含）的最后一个 tick 的 lastPrice，成交量为最后一个 tick 的 volume，因此它包含了集合竞价。

30分钟线以10:00为第一根 bar；其它同1m。

### 1.3. 发布时间和频率

xtquant 目前每3秒推送一次 tick 数据，从09：15开始。因此，从09:15起，本服务就开始对外提供1m, 30m 和实时日线数据，每3秒一次。

但是在早盘集合竞价结束之前，发布的 bar 中，只有 close 可用，其它数据未定义（暂定为0）。第一个有效的 bar，一定同时具备 OHLC和volume, amount。

在09：25~09：30之间以及午盘停牌期间，不发布实时行情数据。


### 1.4. 成交量计算

由于tick携带的是当日累计成交量/成交额，因此在合成1m, 3m 分钟时，需要对 bar 内的实际成交量另行计算。

我们把"上一根 bar 区间内的最后一个 tick.volume"——记作 `ref_volume`。于是在每一个 tick 到达时，用当前 tick.volume - ref_volume 就是本 bar 到现在 tick 为止的成交量。

这里的关键是 ref_volume 的更新：

```
1) ref_volume 初始化值都为零
2) 在新的 tick 到来时，如果 tick 的时间跨越了 bar的时间边界，更新 ref_volume <- last_tick.volume
3) 如果 tick 的时间未跨越，则保持不变。
```

下面用 4 个 tick 把状态走一遍。xtquant 推过来的 `tick.volume` 是当日累计（从 0 起算）。

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

- 历史 issue：[#73](https://github.com/zillionare/qmt-gateway/issues/73)、[#74](https://github.com/zillionare/qmt-gateway/issues/74)
- 修复 PR：[#75](https://github.com/zillionare/qmt-gateway/pull/75)
