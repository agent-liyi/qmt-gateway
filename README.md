# qmt-gateway

**qmt-gateway** 是一个独立的 Windows 网关服务，封装了 [QMT（迅投量化交易终端）](https://www.thinktrader.net/) 的 `xtquant` SDK，将交易、行情等功能以 HTTP / WebSocket API 的形式对外暴露。策略程序可以在任意平台运行，无需依赖 QMT 自带的 Python 环境。

## 功能概览

- **交易 API** — 买入、卖出、撤单，查询委托、成交、持仓、资产
- **实时行情** — WebSocket（`/ws/quotes`）推送合成后的 K 线数据（1 分钟、30 分钟、日线）
- **集合竞价行情** — 独立 WebSocket（`/ws/auction`）推送 09:15–09:30 原始撮合 tick
- **历史数据下载** — 按板块 / 日期下载分钟线 Parquet 文件
- **Web 交易台** — 内置交易界面，含下单表单、速拨盘、持仓 / 委托表格、日志查看器、数据管理
- **初始化向导** — 首次运行逐步引导 QMT 路径、账户、密码、服务器配置
- **自动启动 QMT** — 可选在网关启动时自动拉起 QMT 并填入交易密码，密码加密存储
- **API Key 鉴权** — Web 端使用 session 登录；对外程序化访问使用 `X-API-Key` 长令牌
- **在线更新与回滚** — 从 Web UI 检查版本、一键更新、一键回滚

## 环境要求

| 依赖 | 说明 |
|---|---|
| 操作系统 | Windows 10 / 11 |
| Python | **3.13**（64 位） |
| QMT | 安装在本机，已完成授权 |
| xtquant | 通过配置的 QMT 路径可加载 |

## 快速开始

### 1. 克隆仓库

```bat
git clone https://github.com/zillionare/qmt-gateway.git
cd qmt-gateway
```

### 2. 安装依赖

运行安装脚本，自动检测 Python 3.13+、创建虚拟环境并安装所有依赖：

```bat
setup-venv.bat
```

### 3. 启动服务

```bat
start-qmt-gateway.bat
```

服务启动后访问 **http://localhost:8130**。首次运行会进入初始化向导，引导你配置 QMT 路径、创建管理员账号、设置交易密码和可选的自动启动。

### 4. 使用

- **浏览器** — 打开 `http://localhost:8130`，用向导中设置的管理员密码登录
- **程序化访问** — 在 Web UI 中创建 API Key，请求时带上 `X-API-Key` 请求头

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QMT_GATEWAY_HOST` | `0.0.0.0` | 服务监听地址 |
| `QMT_GATEWAY_PORT` | `8130` | 服务端口 |
| `QMT_GATEWAY_HOME` | `~/.qmt-gateway` | 数据主目录（数据库、日志、导出文件） |

### 命令行参数

```
qmt-gateway --host 0.0.0.0 --port 8130 [--home <path>] [--init-wizard] [--force]
```

| 参数 | 说明 |
|---|---|
| `--host` | 监听地址 |
| `--port` | 端口（覆盖配置文件） |
| `--home` | 数据主目录 |
| `--init-wizard` | 显示初始化向导 |
| `--force` | 强制重新初始化（配合 `--init-wizard` 使用） |

### 数据目录

所有持久化数据存放在数据主目录下：

```
~/.qmt-gateway/
├── data/
│   └── app.db          # SQLite 数据库（配置、委托、持仓、资产）
├── log/
│   └── qmt-gateway.log # 应用日志（自动轮转，每份 10 MB）
└── exports/            # 历史数据导出文件
```

## API 参考

所有 API 端点均需要认证——浏览器 session（Web UI）或 `X-API-Key` 请求头（程序化访问）二选一。

### 认证

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/login` | 登录页面 |
| `POST` | `/auth/login` | 用户名 + 密码登录 |
| `GET` | `/auth/logout` | 登出 |
| `POST` | `/api/api-keys` | 创建 API Key（仅 session 可用） |
| `GET` | `/api/api-keys` | 列出所有 API Key |
| `DELETE` | `/api/api-keys/{key_id}` | 吊销 API Key |

**程序化访问示例：**

```bash
curl -H "X-API-Key: qmt_abc123..." http://localhost:8130/api/trade/asset
```

### 交易

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/api/trade/asset` | 账户资产（现金、市值、总资产、盈亏） |
| `GET` | `/api/trade/positions` | 当前持仓列表 |
| `GET` | `/api/trade/orders` | 当日委托列表 |
| `GET` | `/api/trade/trades` | 当日成交列表 |
| `POST` | `/api/trade/buy` | 买入委托 |
| `POST` | `/api/trade/sell` | 卖出委托 |
| `POST` | `/api/trade/cancel` | 按 qtoid 撤单 |
| `GET` | `/api/trade/connection-status` | QMT 连接状态 |
| `POST` | `/api/trade/restart-qmt` | 重启 QMT 并自动登录 |
| `POST` | `/api/asset/principal` | 修改本金 |

**买入示例：**

```bash
curl -X POST "http://localhost:8130/api/trade/buy" \
  -H "X-API-Key: qmt_..." \
  -d "symbol=000001.SZ&price=12.50&shares=100"
```

**返回示例：**

```json
{
  "success": true,
  "qtoid": "12345",
  "order_id": "67890"
}
```

### 行情数据

#### WebSocket：实时行情 — `ws://host:port/ws/quotes`

推送所有已订阅标的的合成 K 线数据，消息格式为 JSON：

```json
{
  "symbol": "000001.SZ",
  "interval": 60,
  "ts": 1717387200,
  "open": 12.30,
  "high": 12.55,
  "low": 12.28,
  "close": 12.50,
  "volume": 150000,
  "amount": 1867500.0
}
```

支持的 `interval` 值：`60`（1 分钟）、`1800`（30 分钟）、`86400`（日线）。

#### WebSocket：集合竞价 — `ws://host:port/ws/auction`

09:15–09:30 期间推送原始撮合 tick，每条消息包含竞价阶段标识（`auction_a`、`auction_b`、`matching`）：

```json
{
  "type": "auction",
  "symbol": "000001.SZ",
  "phase": "auction_b",
  "price": 12.34,
  "open": 0.0,
  "volume": 0,
  "server_time": "2026-06-12T09:23:45.000"
}
```

#### REST

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/api/v1/quotes/status` | 行情服务状态（是否运行、客户端数量） |

### 股票信息

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/api/stocks` | 获取全部股票列表 |
| `GET` | `/api/stocks/search?stock_search=<关键词>` | 按代码、名称或拼音搜索股票 |
| `GET` | `/api/stock/info?symbol=<代码>` | 获取股票信息及昨收价 |
| `GET` | `/api/stock/resolve?q=<关键词>` | 将关键词解析为股票代码 |

### 历史数据

| 方法 | 端点 | 说明 |
|---|---|---|
| `POST` | `/api/history/minutes/jobs` | 创建分钟线下载任务 |
| `GET` | `/api/history/minutes/jobs/{job_id}` | 查询任务状态 |
| `GET` | `/api/history/minutes/jobs/{job_id}/file` | 下载已完成的 Parquet 文件 |

### 系统管理

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/api/ping` | 健康检查（连通性 + 鉴权） |
| `GET` | `/api/system/version` | 当前版本及更新信息 |
| `POST` | `/api/system/update` | 触发自动更新 |
| `GET` | `/api/system/autostart` | 查询开机自启状态 |
| `POST` | `/api/system/autostart` | 启用 / 禁用开机自启 |
| `GET` | `/api/system/firewall` | 查询防火墙规则状态 |
| `POST` | `/api/system/firewall` | 更新防火墙规则（放行当前端口） |

### 日志流

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/logs/stream` | SSE 端点，实时推送日志更新 |

## 架构

```
┌──────────────────────────────────────────────────┐
│              qmt-gateway (Windows)                │
│                                                   │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │ REST API │  │ WebSocket │  │  Web UI       │  │
│  │ (交易,   │  │ (行情,    │  │  (FastHTML +  │  │
│  │  股票,   │  │  竞价)    │  │   HTMX)       │  │
│  │  系统)   │  │           │  │               │  │
│  └────┬─────┘  └─────┬─────┘  └──────┬───────┘  │
│       │              │               │            │
│  ┌────┴──────────────┴───────────────┴──────┐    │
│  │              服务层                        │    │
│  │  TradeService · QuoteService · StockService│   │
│  │  HistoryDownloadService · Scheduler       │    │
│  └────────────────┬──────────────────────────┘    │
│                   │                                │
│  ┌────────────────┴─────────────────────────┐     │
│  │        xtquant (xttrader + xtdata)        │    │
│  └────────────────┬─────────────────────────┘     │
└───────────────────┼───────────────────────────────┘
                    │
              ┌─────┴──────┐
              │  QMT 客户端 │
              │ (XtMiniQmt) │
              └────────────┘
```

**技术栈：** Python 3.13 · FastHTML · Starlette · uvicorn · SQLite · orjson · pywinauto · bcrypt · cryptography

## 认证机制

网关支持两种认证方式：

1. **Session** — 在 `/login` 页面进行浏览器登录，Web 管理界面使用
2. **API Key** — 长生命周期令牌（前缀 `qmt_`），通过 `X-API-Key` 请求头传递。在 Web UI 中创建，明文仅显示一次，网关只存储 SHA-256 摘要

API Key 不能用于创建或吊销其他 Key——这些操作需要交互式 session。

## 开发

```bat
# 安装开发依赖（pytest, ruff, black）
setup-venv.bat

# 运行测试
.venv\Scripts\python.exe -m pytest -q

# 代码检查
.venv\Scripts\python.exe -m ruff check qmt_gateway/
```

## License

本项目为私有项目，详见 [LICENSE](LICENSE)。
