# qmt-gateway 接口文档

本文档面向 **把 qmt-gateway 作为数据 / 交易通道集成的开发者**，覆盖 HTTP API、WebSocket 与鉴权方式。所有接口返回 `application/json`（除下载接口外），统一响应壳为：

```json
{ "code": 0, "message": "ok", "data": { ... } }
```

---

## 目录

- [基础信息](#基础信息)
- [鉴权](#鉴权)
- [行情接口](#行情接口)
- [股票基础信息](#股票基础信息)
- [交易接口](#交易接口)
- [历史分钟线下载](#历史分钟线下载)
- [系统管理](#系统管理)
- [API Key 管理](#api-key-管理)
- [错误码](#错误码)
- [典型调用流程](#典型调用流程)

---

## 基础信息

| 项       | 说明                                                                  |
| -------- | --------------------------------------------------------------------- |
| 默认监听 | `http://127.0.0.1:<server_port>`（端口见系统管理 `/api/system/port`） |
| 数据来源 | QMT / xtquant（`xtdata` 行情，`xttrader` 交易）                       |
| 鉴权方式 | 浏览器会话（cookie）或 `X-API-Key` 头                                 |
| 实时推送 | WebSocket `/ws/quotes`（1m / 30m / 1d K 线）                          |

---

## 鉴权

qmt-gateway 同时支持 **两种身份**：

1. **Session 登录**（浏览器 / 表单登录后由 cookie 维持）
   - 登录入口：`POST /auth/login`（表单：`username`、`password`、`auto_login`）
   - 登出：`POST /auth/logout`
   - 修改密码：`POST /auth/change-password`
2. **API Key**（无状态，供外部脚本使用）
   - 在请求头加 `X-API-Key: qmt_xxx...`
   - 颁发 / 列表 / 吊销见 [API Key 管理](#api-key-管理)

服务端在每个业务接口通过 `require_api_key_or_session(request)` 做校验：

- 命中 session → 通过
- 否则读 `X-API-Key` 头 → 校验 `sha256` 摘要 → 通过
- 都没有 → 返回 `401 {"code": 1, "message": "未登录或缺少 API key"}`

> **本机限制**：部分敏感辅助接口（重启 QMT 的 helper 协议）通过 `_require_local_request` 限制仅 `127.0.0.1` / `::1` / `localhost` 可访问。

---

## 行情接口

### `GET /api/ping`

轻量级连通性 + 鉴权体检。**初始化向导阶段**也可用，副作用为零。

```http
GET /api/ping HTTP/1.1
X-API-Key: qmt_xxx
```

```json
{ "code": 0, "message": "ok", "data": { "ok": true, "latency_ms": 3 } }
```

### `GET /api/v1/quotes/status`

返回实时行情服务状态与在线 WebSocket 客户端数。

```json
{ "code": 0, "data": { "running": true, "clients": 2 } }
```

### `WS /ws/quotes`

实时推送通道。客户端协议：

| 方向  | 消息                                             | 说明                                                                 |
| ----- | ------------------------------------------------ | -------------------------------------------------------------------- |
| C → S | `{"action":"subscribe","symbols":["600000.SH"]}` | 当前仅做日志，**不过滤推送**（所有客户端都收到全市场 tick 聚合结果） |
| C → S | `{"action":"ping"}`                              | 心跳                                                                 |
| S → C | `{"action":"pong"}`                              | 心跳应答                                                             |
| S → C | K 线消息（见下）                                 | 每次 xtquant tick 触发一条                                           |

**K 线消息结构**（每条消息同时含三个级别，每次 tick 触发一条更新）：

```json
{
  "symbol": "600000.SH",
  "timestamp": "2026-06-12T09:31:25.123456",
  "1m":  { "open": 10.10, "high": 10.15, "low": 10.08, "close": 10.12, "volume": 12345, "amount": 125000.0, "time": "2026-06-12T09:31:00" },
  "30m": { "open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "amount": ..., "time": "..." },
  "1d":  { "open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "amount": ..., "time": "..." }
}
```

qmt-gateway 使用 orjson 来实现 json.dump.

> **量纲规则**（xtquant tick 字段语义）：
> - xtquant tick 中 `volume` / `amount` 是**当日累计成交**（自开盘起累计），不是本 tick 的 delta。
> - K 线内不同级别采用不同公式：
>   - **1d 整日 = 自开盘累计** → `bar.volume = tick.volume`
>   - **日内级别（1m / 30m / 其它）** → `bar.volume = tick.volume - prev_bar.volume`


更详细算法说明，包括推送时机与频繁见 [docs/know-how.md](know-how.md#实时K线合成)。

**Python 客户端示例**：

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8000/ws/quotes") as ws:
        await ws.send(json.dumps({"action": "ping"}))
        async for msg in ws:
            data = json.loads(msg)
            if data.get("action") == "pong":
                continue
            print(data["symbol"], data["1m"]["close"], data["1m"]["volume"])

asyncio.run(main())
```

---

## 股票基础信息

| 方法 | 路径                                  | 用途                                                             |
| ---- | ------------------------------------- | ---------------------------------------------------------------- |
| GET  | `/api/stocks`                         | 列出全部已缓存股票                                               |
| GET  | `/api/stocks/search?stock_search=...` | 关键字搜索（用于前端下拉补全）                                   |
| GET  | `/api/stock/info?symbol=600000.SH`    | 拉取单只股票的 Speed Dial HTML，响应头 `X-Last-Close` 返回昨收价 |
| GET  | `/api/stock/resolve?q=...`            | 智能解析（代码 / 中文名 / 拼音）                                 |

`/api/stock/resolve` 返回示例：

```json
{ "ok": true, "symbol": "600000.SH", "name": "浦发银行", "last_close": 9.87 }
```

支持前缀匹配，命中多只时返回 `{ "ok": false, "ambiguous": true, "count": N }`。

---

## 交易接口

> 交易委托与撤单需要 session 登录 **或** API Key。QMT 必须已连接（见 `/api/trade/connection-status`）。

### 查询

| 方法 | 路径                                            | 说明                                                                                           |
| ---- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| GET  | `/api/trade/asset`                              | 账户资金快照（总资产 / 可用 / 冻结 / 持仓市值 / 当日盈亏）                                     |
| GET  | `/api/trade/positions?view=json\|table`         | 当前持仓；`view=table` 返回 HTML 片段                                                          |
| GET  | `/api/trade/orders?status=all&view=json\|table` | 委托列表；`status` 可取 `all` / `pending` / `partial` / `filled` / `cancelled` / `rejected` 等 |
| GET  | `/api/trade/trades`                             | 当日成交                                                                                       |
| GET  | `/api/trade/connection-status`                  | QMT 客户端连接状态                                                                             |

`/api/trade/asset` 返回示例：

```json
{ "code": 0, "data": { "principal": 1000000, "total": 1023500.5, "profit": 23500.5,
  "profit_ratio": 2.35, "cash": 234567.0, "market_value": 788933.5, "frozen_cash": 0.0 } }
```

`/api/trade/positions` 列表元素：

```json
{ "symbol": "600000.SH", "name": "浦发银行", "shares": 1000, "avail": 1000,
  "price": 10.20, "cost": 9.80, "profit_ratio": 4.08, "float_profit": 400.0,
  "market_value": 10200.0, "hold_cost": 9800.0, "position_ratio": 1.0 }
```

### 委托 / 撤单

| 方法 | 路径                | 必填参数                    | 说明                                                |
| ---- | ------------------- | --------------------------- | --------------------------------------------------- |
| POST | `/api/trade/buy`    | `symbol`, `price`, `shares` | 限价买入；可附 `qtoid`（策略订单号）、`strategy_id` |
| POST | `/api/trade/sell`   | `symbol`, `price`, `shares` | 限价卖出                                            |
| POST | `/api/trade/cancel` | `qtoid`（或 `order_id`）    | 撤单；可加 `view=table` 撤单后回 HTML 片段          |

```bash
# 买入 1000 股 600000.SH @ 10.20
curl -X POST http://127.0.0.1:8000/api/trade/buy \
  -H "X-API-Key: qmt_xxx" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "symbol=600000.SH&price=10.20&shares=1000&qtoid=strat-001"
```

成功响应：

```json
{ "code": 0, "data": { "success": true, "order_id": "12345", "qtoid": "strat-001" } }
```

### QMT 重启

| 方法 | 路径                                                        | 用途                                                                               |
| ---- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| POST | `/api/trade/restart-qmt`                                    | 重启 QMT 客户端并自动登录；可传 `password`，缺省时尝试用会话派生的密钥解密已存密码 |
| GET  | `/api/trade/restart-qmt/has-password`                       | 探测当前会话是否持有可解密的 QMT 密码                                              |
| GET  | `/api/trade/restart-qmt/password?token=...`                 | **仅本机** 一次性获取重启密码（helper 用）                                         |
| POST | `/api/trade/restart-qmt/helper-status?token=...&status=...` | **仅本机** helper 状态回写                                                         |

> 30 秒超时，后台执行；返回结构为 `{ "success": bool, "error": "..." }`。

### 本金管理

| 方法 | 路径                   | 必填参数    | 说明                                                   |
| ---- | ---------------------- | ----------- | ------------------------------------------------------ |
| POST | `/api/asset/principal` | `principal` | 录入 / 修改初始本金；写入 `assets` 表，`principal > 0` |

---

## 历史分钟线下载

异步任务模型：

| 方法 | 路径                                      | 说明                                                                          |
| ---- | ----------------------------------------- | ----------------------------------------------------------------------------- |
| POST | `/api/history/minutes/jobs`               | 创建下载任务（参数：`trade_date=YYYY-MM-DD`，`period=1m`，`universe=ashare`） |
| GET  | `/api/history/minutes/jobs/{job_id}`      | 查询任务状态 / 进度                                                           |
| GET  | `/api/history/minutes/jobs/{job_id}/file` | 下载产物（**parquet**，zstd 压缩）                                            |

```bash
# 创建任务
curl -X POST http://127.0.0.1:8000/api/history/minutes/jobs \
  -H "X-API-Key: qmt_xxx" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "trade_date=2026-06-12&period=1m&universe=ashare"

# 轮询状态
curl http://127.0.0.1:8000/api/history/minutes/jobs/<job_id> -H "X-API-Key: qmt_xxx"

# 下载结果
curl -OJ http://127.0.0.1:8000/api/history/minutes/jobs/<job_id>/file -H "X-API-Key: qmt_xxx"
```

任务状态：`pending` / `running` / `success` / `failed`。

任务响应字段（参考 [services/history_download_service.py](../qmt_gateway/services/history_download_service.py) 中的 `DownloadJob`）：

| 字段                        | 说明                                         |
| --------------------------- | -------------------------------------------- |
| `job_id`                    | 任务 UUID                                    |
| `trade_date`                | 交易日（`YYYY-MM-DD`）                       |
| `period`                    | K 线周期（当前仅支持 `1m`）                  |
| `universe`                  | 股票范围（当前仅支持 `ashare`）              |
| `status`                    | `pending` / `running` / `success` / `failed` |
| `total_symbols`             | 总股票数（任务开始后回填）                   |
| `finished_symbols`          | 已处理股票数（粗粒度进度）                   |
| `rows`                      | 已写入 parquet 的行数                        |
| `file_name`                 | parquet 文件名（含 `<date>_<jobid[:8]>`）    |
| `error`                     | 失败原因（仅在 `failed` 时有值）             |
| `created_at` / `updated_at` | ISO 时间戳                                   |

> **当前没有 `progress` 字段**——如有进度展示需求，请用 `finished_symbols / total_symbols` 自算。

---

## 系统管理

> 下列接口使用 `@login_required`，**仅 session 登录**可访问（不接受 API key）。

| 方法 | 路径                                  | 用途                                 |
| ---- | ------------------------------------- | ------------------------------------ |
| GET  | `/api/system/version`                 | 当前版本 / 远端最新版本 / 是否有更新 |
| POST | `/api/system/version/check`           | 主动触发版本检查                     |
| POST | `/api/system/update`                  | 启动后台更新任务，返回 `task_id`     |
| GET  | `/api/system/update/status/{task_id}` | 轮询更新进度                         |
| POST | `/api/system/rollback`                | 回滚到上一版本                       |
| GET  | `/api/system/autostart`               | 开机自启状态                         |
| POST | `/api/system/autostart`               | 启用 / 禁用（表单 `enabled=true      | false`） |
| GET  | `/api/system/port`                    | 当前服务端口                         |
| GET  | `/api/system/firewall`                | 防火墙规则是否存在                   |
| POST | `/api/system/firewall`                | 更新防火墙端口（表单 `port=...`）    |

更新任务返回结构：

```json
{ "code": 0, "data": { "status": "running", "progress": 42 } }
```

完成后 `result` 包含 `success`、`old_version`、`new_version`、`error`。

---

## API Key 管理

> 这些接口要求**已登录**（不接受 API key 自身调用），用来防止 token 自我繁殖。

| 方法   | 路径                     | 说明                                                        |
| ------ | ------------------------ | ----------------------------------------------------------- |
| POST   | `/api/api-keys`          | 颁发新 key（参数 `name`）；**plaintext 仅在创建时返回一次** |
| GET    | `/api/api-keys`          | 列出全部 key（不含明文 / hash）                             |
| DELETE | `/api/api-keys/{key_id}` | 吊销指定 key                                                |

```bash
# 颁发
curl -X POST http://127.0.0.1:8000/api/api-keys \
  --cookie "session=..." \
  -d "name=my-script"

# 响应（明文仅此一次，请立即保存）
{ "code": 0, "data": { "id": "k_abc", "name": "my-script",
  "key_prefix": "qmt_a1b2c3d4", "plaintext": "qmt_a1b2c3d4...." } }
```

> 存储：服务端仅保留 `sha256(plaintext)` 摘要，列表只回显 `key_prefix` 前 12 字符。

---

## 错误码

| `code` | 含义                  | 典型场景                                                                 |
| ------ | --------------------- | ------------------------------------------------------------------------ |
| 0      | 成功                  | —                                                                        |
| 1      | 业务失败              | 参数错误 / QMT 未连接 / 撤单失败 / 任务不存在 / 资源冲突（任务尚未完成） |
| 401    | 未登录或 API key 无效 | 缺少 `X-API-Key`、key 已被吊销、session 过期                             |
| 403    | 权限不足              | helper 接口被远端调用（要求 127.0.0.1）                                  |
| 404    | 资源不存在            | `job_id` / `key_id` 不存在                                               |
| 409    | 资源状态冲突          | 下载任务尚未完成时再次请求文件                                           |
| 500    | 服务器异常            | QMT 调用失败、数据库异常等                                               |

> HTTP 状态码与 `code` 同时出现；优先以 HTTP 状态码判断调用成败，再看 `code` 区分业务类型。

---

## 典型调用流程

### 1. 准备

```bash
# 浏览器登录 -> 拿 session cookie
# 然后在「系统设置」里创建一个 API key 并保存 plaintext
```

### 2. 健康检查

```bash
curl http://127.0.0.1:8000/api/ping -H "X-API-Key: $QMT_KEY"
```

### 3. 解析股票

```bash
curl 'http://127.0.0.1:8000/api/stock/resolve?q=600000' -H "X-API-Key: $QMT_KEY"
```

### 4. 订阅实时 K 线

```python
# 参见「行情接口 → Python 客户端示例」
```

### 5. 下单

```bash
curl -X POST http://127.0.0.1:8000/api/trade/buy \
  -H "X-API-Key: $QMT_KEY" \
  -d "symbol=600000.SH&price=10.20&shares=1000&qtoid=strat-001"
```

### 6. 查持仓 / 委托 / 成交

```bash
curl http://127.0.0.1:8000/api/trade/asset      -H "X-API-Key: $QMT_KEY"
curl http://127.0.0.1:8000/api/trade/positions  -H "X-API-Key: $QMT_KEY"
curl http://127.0.0.1:8000/api/trade/orders     -H "X-API-Key: $QMT_KEY"
curl http://127.0.0.1:8000/api/trade/trades     -H "X-API-Key: $QMT_KEY"
```

### 7. 下载历史分钟线

参见「[历史分钟线下载](#历史分钟线下载)」三步：创建 → 轮询 → 下载文件。

---

## 注意事项

- **量纲**：xtquant 的 `volume` / `amount` 是**当日累计**。所有 K 线 / 历史下载产物沿用此约定，量化策略层请按此解释。
- **时区**：所有时间戳为本地时间（Asia/Shanghai）。
- **节流**：实时推送是 tick 驱动，**未做语义节流**——每个 tick 即产生一条 WebSocket 消息，同一根 bar 会被推送多次。后端已用 `asyncio.Queue` + 单 worker 批量广播（[apis/quotes.py](../qmt_gateway/apis/quotes.py)）做传输层优化，缓解事件循环压力；但**不会**主动聚合同 symbol 的多条 tick 合并为单条推送。客户端如需去重，建议按 `(symbol, bar.time)` 维度去重。
- **QMT 不可用时**：交易接口会返回 `{ "code": 1, "message": "QMT 未连接" }` 类业务错误。脚本侧应做退避重试。
- **本机限制**：`_require_local_request` 保护的几只 helper 接口必须从本机调用；远端调用返回 403。
