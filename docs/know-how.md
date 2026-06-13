## 1. xtquant 全推数据与 K 线合成

本节解释从 xtquant 订阅的全推数据，如何合成为1m, 30m 和 日线的算法。具体实现是 [qmt_gateway/services/quote_service.py](../qmt_gateway/services/quote_service.py) 中 `_update_bar` 的合成逻辑

### 1.1. xtquant 全推数据行为

xtquant 全推数据称为 tick，每个 tick 中字段含义见下表。

#### 1.1.1. 字段语义
xtquant 在 `subscribe_whole_quote` / `subscribe_quote` / `get_full_tick` / `get_market_data_ex` 等所有公开行情接口中保持同一套字段语义：

| 字段          | 含义                            |
| ------------- | ------------------------------- |
| `lastPrice`   | 最新价                          |
| `open`        | 当日集合竞价时的撮合价          |
| `high`        | `low`                           | 当日累积的极值 |
| `volume`      | **当日累计成交量（股）**        |
| `amount`      | **当日累计成交额（元）**        |
| `openInt`     | 累计持仓量（期货）              |
| `lastClose`   | 前一日收盘价，已复权（前）      |
| `server_time` | 该tick 归属时间，由 server 决定 |
| `stockStatus` | 竞价阶段，取值为0, 2,3,4等      |

tick 数据还有买卖5档数据，暂略。

以上字段在不同时间段，取值方法和含义有所不同。

**注意** 由于 xtquant 是每3秒发送一个 tick，实际上它是一个假的 tick 数据（是把3秒内所有的成交进行了合成）；所以 max(lastPrice) != high。

#### 1.1.2. xtquant 的推送行为

在**订阅 xtquant 全推数据时**，订阅者（在本项目中即 qmt-gateway 自己）会立刻得到一组tick 数据。该数据中，`server_time`的`time`部分为0， `lastPrice` 与 `lastClose`有值。

**09:15起到09:19:59.999止**， 进入 auction_a 阶段，此时 lastPrice 有意义。此时虚假报单较多，价格仅共参考。此时 OHLV等字段都为0，stockStatus = 2

**09:20到09:24:59.999止**， 进入 auction_b 阶段，此时各字段与 auction_a 相同。

**09:25:00**，竞价撮合结果，此时 lastPrice, OHLV都有值，O=H=L=lastPrice，stockStauts = 3

**09:25:01到09:29:59.999***，此阶段没有数据

**09:30~**，进入连接竞价阶段。

注意上述时间是指`server_time`，订阅者实际上将在随后的几秒中陆续收到前一个`server_time`的 tick，具体时间不定。09:25:00这一刻的撮合价，在观测中最才等待9秒才收到。

### 1.2. qmt-gateway 推送时机和频率

在收到每一个 tick 时，都会触发一次推送（auction 期间原样照送的 tick 和连接竞价期间合成的 bar）。

qmt-gateway 在集合竞价期间，原样（指未合成，但字段有减少，个别字段重命名）推送收到的每一个 tick 数据。此时走`ws/auction`通道。最重要的字段是 phase，它对应 xtquant.tick 中的 stockStatus，客户端需要根据它的值来确定其它字段的真实含义。

在连续竞价（09：30起）期间，推送带 OHLC，volume, amount 的 k 线数据。该数据是合成数据。此时走`/ws/quotes`通道。

### 1.3. k线重采样

因此 `/ws/quotes` 的第一根 1m bar 落在 **09:30:00 第一个 tick 触发的 09:31 bar**——它会自然包含集合竞价的成交（因为 `tick.volume` 是当日累计，09:30:00 第一个 tick 的 volume 已经把集合竞价撮合量算进去了）。

集合竞价撮合行情（09:15 ~ 09:29:59）走独立 endpoint **`/ws/auction`**，**每 tick 一条**地原样转发关键字段（`symbol / price / open / high / low / volume / amount / stock_status / phase`），不做 K 线合成。客户端可在 09:25 撮合那一帧（`phase == "matching"` 且 `open != 0` 且 `volume > 0`）立刻拿到稳定开盘价，无需等到 09:30。

这里要区分成交量字段和价格字段：首根日内 bar（09:31 的 1m、10:00 的 30m）的 `volume/amount` 会自然承接集合竞价的累计成交；价格维度中，`open` 直接取 09:25 撮合确定的开盘价，`high/low` 取该 bar 右端点之前最后一个 `tick.high/tick.low`（它们是当日累计极值，因此可能包含 09:25 的撮合价），`close` 则仍取该 bar 区间右界前最后一个 `tick.lastPrice`。




#### 1.3.1. k 线的时间索引

A 股标准分钟 K 线的语义：**bar.time = 区间右端点（结束时刻）**。聚宽、Tushare、xtquant 自带的历史 K 线、通达信、Wind 全部按此对齐。

- 09:30:00 ~ 09:30:59 的成交属于 **09:31** bar
- 09:31:00 ~ 09:31:59 的成交属于 **09:32** bar
- 一直到 14:59:00 ~ 14:59:59 → **15:00** bar（当日最后一根）

实现层面：日内级别用 `bar_timestamp = ((ts // interval) + 1) * interval`，把"区间内任意秒"映射到该区间的右端点。日线 (`interval=86400`) 直接用 `now.replace(hour=0, minute=0, second=0)`，bar.time 取当日 0 点。


#### 1.3.2. Open 重采样

分钟线重采样示例如下：

| 时间索引 | 采样方法                   | 说明                 |
| -------- | -------------------------- | -------------------- |
| 09:31    | 集合竞价确定的开盘价       | 09:31为分钟线第1 bar |
| 09:32    | 09:31:00起，第一个 tick.lp | NA                   |

30分钟线重采样示例如下：

| 时间索引 | 采样方法                        | 说明                  |
| -------- | ------------------------------- | --------------------- |
| 10:00    | 集合竞价确定的开盘价            | 第1 bar要使用集合竞价 |
| 10:30    | 10:00:00.000 起，第一个 tick.lp | na                    |

日线重采样的open 即为集合竞价确定的开盘价。

#### High/Low 重采样

分钟线重采样示例如下(以high 为例，low 以此类推）：

| 时间索引 | 采样方法                                | 说明                                                                                                                                                |
| -------- | --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 09:31    | 到09:30:59.999的最后一个 tick.high      | tick.high 是累积的                                                                                                                                  |
| 09:32    | [09:31:00, 09:31:59.999]的 max(tick.lp) | tick.high 是当日累积的（包含之前 bar 的数据），所以不能直接用于非首根 bar，只能用 lastPrice 估算区间极值，会导致估算 high 低于实际该区间的真实 high |

30分钟线重采样示例如下：

| 时间索引 | 采样方法                                   | 说明                                                   |
| -------- | ------------------------------------------ | ------------------------------------------------------ |
| 10:00    | 到09:59:59.999时的最后一个 tick.high       | tick.high 是累积的                                     |
| 10:30    | [10:00:00,10:29:59.999]期间的 max(tick.lp) | 同上，此处的 high 不完全精确。估算 high 可能低于真实 high |

日线重采样的high/low 即为最后一个 tick.high/low

#### Close 重采样

close 是到该级k 线时间右界（比如09:30:59.999， 09：59：59.999）时，最后一个 tick 的 lastPrice。对日线，即为最后一个 tick 的 lastPrice

#### Volume/Amount 重采样

由于tick携带的是当日累计成交量/成交额，因此在合成1m, 30m 分钟时，需要对 bar 内的实际成交量另行计算。

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
