用来进行初始化时的回归，以正面测试为主，有条件的情况下，适当做一点负面测试。

## 测试环境

1. 要求用户安装 qmt，并提供安装路径。
2. 用户在执行测试时，通过命令行参数，传入安装路径、账号和密码。管理员密码自行生成
3. 测试前，脚本自动备份现有配置数据，在测试完成之后恢复。即使测试异常中断，也要确保自动恢复到测试前状态。

## 测试用例

测试用例编号约定 `TC-<group>-<seq>`，覆盖范围参考：

- 路由层：[`qmt_gateway/app.py`](qmt_gateway/app.py) 中的 `GET /init-wizard`、`GET /init-wizard?force=true`、`POST /init-wizard/step/{n}`、`POST /init-wizard/complete`、`POST /init-wizard/retry-startup`。
- UI 层：[`qmt_gateway/web/pages/init_wizard.py`](qmt_gateway/web/pages/init_wizard.py) 与 [`qmt_gateway/init_wizard.py`](qmt_gateway/init_wizard.py)。
- 辅助层：[`qmt_gateway/qmt_init_helpers.py`](qmt_gateway/qmt_init_helpers.py)、[`qmt_gateway/core/process_utils.py`](qmt_gateway/core/process_utils.py)、[`qmt_gateway/core/crypto_utils.py`](qmt_gateway/core/crypto_utils.py)、[`qmt_gateway/services/trade_service.py`](qmt_gateway/services/trade_service.py) 中 `_wizard_restart_qmt` / `restart_and_login`。
- 回归基线：[`tests/test_init_wizard.py`](tests/test_init_wizard.py)（718 行，5 大行为分组）已覆盖的每条用例都必须在端到端脚本里有对应入口。

关联 issue：

- #15 init-wizard 连接测试失败时自动启动 QMT 并重试（已关闭，行为基线）
- #19 Init-Wizard 完成初始化时显示 QMT 启动进度对话框与重试按钮（已关闭，行为基线）
- #16 QMT 交易密码加密存储与自动登录（已关闭，加密基线）
- #10 重启 qmt 交易服务，并自动填入交易密码（进行中，运行时一致性）
- #29 启动进程时，自动启动 qmt（进行中，进程启动期）
- #32 init-wizard 允许空管理员密码（进行中，本计划新增 TC-3-02 覆盖）
- #33 init-wizard password 输入框宽度问题（已关闭，TC-10-02 回归）
- #12 安全增强（已关闭，TC-8 系列加密与日志约束）

### 1. 全新安装后的首次初始化（happy path）

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-1-01 | 首次访问 `/` | 干净数据库（无 settings）→ `GET /` | 302 → `/init-wizard`，渲染 step 1 |
| TC-1-02 | 5 步向导无 QMT 密码 | 走完 5 步，**不**填 `qmt_password`、**不**勾 `auto_start_qmt` → `POST /init-wizard/complete` | 302 → `/`；DB 写入 `user` / `settings` / `assets`；`qmt_password_encrypted` 为空；`init_completed=True` |
| TC-1-03 | 含 QMT 密码 + auto_start | 走完 5 步，填 `qmt_password`，勾选 `auto_start_qmt` | `qmt_password_encrypted` / `qmt_password_salt` / `qmt_password_auto_start` 全部写入；`init_completed=True` |
| TC-1-04 | 含 QMT 密码但不勾 auto_start | 填 `qmt_password` 不勾 `auto_start_qmt` | 加密字段写入；`qmt_password_auto_start` 为空；`auto_start_qmt=False` |
| TC-1-05 | 步骤间"上一步" | 在 step 2/3/4/5 点击"上一步" | 步骤指示器状态正确；表单回填先前输入 |
| TC-1-06 | 跳过 welcome 直接点"下一步" | step 1 仅有说明文字 | 进入 step 2，无必填校验 |
| TC-1-07 | 本金为 0 / 负数 | `principal="0"` 或 `"-1"` | `_commit_wizard_settings` 落到默认值 `1000000` |

### 2. 强制重新初始化（force=true）

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-2-01 | force GET 不写 DB（对应 `test_force_get_*`） | 已 `init_completed=True` → `GET /init-wizard?force=true` | 200；settings / user / assets **任何字段不变** |
| TC-2-02 | force GET 后放弃 | 打开后关闭浏览器（不调 complete） | `check_init_required()` 仍返回 `False`；主应用继续可用 |
| TC-2-03 | force GET 预填 | 已 init 的 settings 含旧值 → `GET ?force=true` | `_wizard_data` 含 server_port / log_* / qmt_account_id / qmt_path / xtquant_path / username |
| TC-2-04 | force 模式 no-op 完成 | 预填后不修改任何字段 → `POST complete` | 写入值与原值一致，行为等价于 no-op |
| TC-2-05 | force 模式部分修改 | 预填后仅修改本金 / 端口 | 仅修改字段变化，未触碰字段保持 |

### 3. 密码与表单校验

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-3-01 | 两次密码不一致 | step 2 提交 `password≠password_confirm` | 回到 step 2，红色错误条；OOB 隐藏进度对话框 |
| TC-3-02 | 管理员空密码（关联 #32） | step 2 `password` / `password_confirm` 都留空 → 点"下一步" | 阻止进入下一步，提示"请输入密码" |
| TC-3-03 | 用户名修改为非 admin | step 2 把 `username` 改为 `trader` → complete | 按 `trader` 创建或更新 `users` 行；`is_admin` 取默认值 |
| TC-3-04 | `qmt_account_id` 留空 | step 5 留空 → 提交 | HTML `required` 拦截；脚本绕过时 `wizard_complete` 报错并回滚 |
| TC-3-05 | `qmt_path` 留空 | step 5 留空 → 提交 | 同上 |
| TC-3-06 | `principal` 含非法字符 | `principal="abc"` | 落库时按 `1000000` 默认值处理 |

### 4. QMT 路径解析

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-4-01 | 路径指向 `userdata_mini` | `qmt_path = C:\brokerQMT\userdata_mini` | `resolve_qmt_executable` 找到 `bin.x64\XtItClient.exe` |
| TC-4-02 | 路径指向父目录 | `qmt_path = C:\brokerQMT` | 同上 |
| TC-4-03 | 路径不存在 | `qmt_path = C:\no\such\path` | `probe_qmt_path` 返回 `valid=False`，wizard 失败并回滚 |
| TC-4-04 | 路径无 `userdata_mini` | `qmt_path = C:\some\dir` | `probe_qmt_path` 报"目录中应包含 userdata_mini" |
| TC-4-05 | `bin.x64` 缺失 | 仅有 `userdata_mini` 无 `bin.x64\XtItClient.exe` | `FileNotFoundError` → 失败回滚 |
| TC-4-06 | `qmt_path` 含 `~` 波浪号 | `qmt_path = "~/QMT/userdata_mini"` | 解析时 `expanduser` + `resolve`，得到绝对路径 |

### 5. xtquant 连接 + QMT 自愈

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-5-01 | xtquant 一次成功 | QMT 已登录 → `POST complete` | 直接落库（不走自愈） |
| TC-5-02 | QMT 未运行 + 有密码（对应 `test_recovery_succeeds_when_trade_service_restart_qmt`） | `is_qmt_process_running()=False` + `qmt_password` 已填 | `_wizard_restart_qmt` 启动 → 填密码 → 验证 → 成功 |
| TC-5-03 | QMT 已运行但未登录成功（对应 `test_recovery_forces_restart_when_qmt_is_running_but_connection_fails`） | 进程在但 `require_xtdata` 失败 | 强制 kill → relaunch → auto_login → 成功 |
| TC-5-04 | 路径不合法导致启动失败（对应 `test_recovery_reports_invalid_path_without_launching`） | 路径无 `userdata_mini` | 走 failure fragment + 回滚；显示"重试启动 QMT"和"返回修改配置" |
| TC-5-05 | 启动成功但 xtdata 等待超时 | 启动 OK，但 `require_xtdata` 仍失败 | 走 wait dialog + `auto_retry=True`（不立即落库） |
| TC-5-06 | 启动成功 + auto-retry 触发 complete（对应 `test_retry_startup_success_branch_skips_xtdata_wait`） | 后台重启任务完成 | 显示"QMT 连接成功，正在完成初始化..."，1 秒后自动 POST `/init-wizard/complete` |
| TC-5-07 | 无 QMT 密码 + xtquant 不可用（对应 `test_complete_without_qmt_password_skips_connection_test`） | `require_xtdata` 抛错 + `qmt_password=""` | 跳过连接测试，直接落库；`init_completed=True` |
| TC-5-08 | 有密码但 `auto_start_qmt=False`（对应 `test_complete_with_password_but_no_auto_start_skips_restart`） | 填密码不勾 auto_start | 仅加密保存，不做自动启动/重连；`qmt_password_auto_start=""` |

### 6. 进度对话框与重试

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-6-01 | 点击"完成初始化"立即弹窗 | 提交时 `qmt_password` 非空 | 进度对话框立即显示，spinner + "正在自动启动 QMT 客户端并测试连接，请稍候..." |
| TC-6-02 | "重试"按钮 30 秒累计启用（对应 `test_init_wizard_page_script_uses_cumulative_30_second_retry_window`） | 等候 30 秒 | 重试按钮 `disabled → enabled`；累计计时（auto-retry 不重置 `_progressStartedAt`） |
| TC-6-03 | "返回修改配置"按钮 | 在对话框中点击 | `GET /init-wizard/step/5`，回到 step 5 表单 |
| TC-6-04 | 启动失败显示原因（对应 `test_retry_startup_failure_branch_uses_fast_auto_retry`） | `restart_qmt` 返回 error | 对话框内容替换为 ⚠ 错误 + "重试" + "返回修改配置"；`setTimeout` 1 秒自动重试 |
| TC-6-05 | HTMX 重定向（对应 `test_complete_without_qmt_password_uses_hx_redirect_for_htmx_requests`） | 通过 `HX-Request: true` 完成 | 响应 `HX-Redirect: /`；客户端在 `htmx:beforeSwap` 中 `window.location.href` 跳转 |
| TC-6-06 | 进度对话框 OOB 保留 | 多次重试 | 模态框 `#wizard-progress-modal` 持续存在，不被 HTMX 交换覆盖；`resetTimer` 标志区分手动重试与 auto-retry |

### 7. 原子性与回滚（对应 `_snapshot_wizard_state` / `_rollback_wizard_state`）

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-7-01 | xtquant 失败回滚 settings（对应 `test_complete_rolls_back_when_xtquant_test_fails`） | 提交新 settings → `require_xtdata` 抛错 | DB `settings` 与提交前 `to_dict()` 完全一致 |
| TC-7-02 | xtquant 失败回滚 user 密码 | 同时改了 `password` → 失败 | `user.password_hash` 保持原值 |
| TC-7-03 | xtquant 失败回滚 asset 本金 | 同时改了 `principal` → 失败 | `assets` 表 `default portfolio` 当天那一行保持原值 |
| TC-7-04 | xtquant 失败 `init_completed` 不翻转 | 已 `init_completed=True` → 失败 | `init_completed` 仍为 `True` |
| TC-7-05 | `wizard_data` 部分填入后回滚（对应 `test_complete_rolls_back_settings_when_test_fails_after_partial_form`） | 先 `POST step/2`，再 `complete` 失败 | settings / user / asset 全部为原值 |
| TC-7-06 | 顶层异常回滚 | 任意未捕获异常 → `except` 块 | `_rollback_wizard_state(snapshot)` 被调用；`Div("初始化失败: ...")` 渲染 |

### 8. 加密与安全（关联 #10 / #12 / #16 / #29）

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-8-01 | QMT 密码加密存储 | init 提交含 `qmt_password` | `qmt_password_encrypted` = `Fernet(token)`；`qmt_password_salt` = 16 字节 hex |
| TC-8-02 | auto_start 密码机器密钥加密（对应 [`tests/test_crypto_auto_start.py`](tests/test_crypto_auto_start.py)） | 勾选 `auto_start_qmt` | `qmt_password_auto_start` = `Fernet(machine_key)`；同明文两次加密密文不同；解密回明文 |
| TC-8-03 | 登录密码修改后重加密（对应 [`tests/test_security_features.py`](tests/test_security_features.py)） | 完成 init → `/auth/password` 改登录密码 | QMT 密码被用新登录密码重新加密，旧 `salt` 替换为新 `salt` |
| TC-8-04 | QMT 密码修改流程 | 登录后 `POST /auth/qmt-password` | `settings.qmt_password_encrypted` 更新；`session.qmt_decrypt_key` 更新 |
| TC-8-05 | 日志 / 响应不泄露明文 | 任何接口响应 + log | `qmt_password` 明文不出现；`password` 字段不回显；`secret` / `token` 不出现 |
| TC-8-06 | 派生密钥缓存 | 登录时计算 `qmt_decrypt_key` 存 session | 后续 `/api/trade/restart-qmt` 自动用此密钥解密，无需重新输入 |

### 9. 运行时自动启动（关联 #29）

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-9-01 | 启动服务时 QMT 未运行 + auto_start（对应 [`trade_service.startup_event`](qmt_gateway/apis/trade.py)） | 干净启动 + `settings.auto_start_qmt=True` | 先 `connect` → 失败 → `try_auto_start_qmt` → 重连 |
| TC-9-02 | auto_start 失败不阻断服务 | QMT 启不来 / 密码错 | 服务仍启动；用户可通过 web "重新连接" 按钮手动重试 |
| TC-9-03 | auto_start 最多重试 2 次 | `_auto_start_max_retries=2` | 失败超过 2 次后停止尝试，避免死循环 |
| TC-9-04 | 启动时无 auto_start | `auto_start_qmt=False` | 不调用 `try_auto_start_qmt` |

### 10. UI 渲染与回归

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-10-01 | 步骤指示器样式 | 访问 step 3 | 1 ✓ 2 ✓ 3 高亮（外环） 4 灰 5 灰；连接线 1-2、2-3 用主色，3-4、4-5 灰 |
| TC-10-02 | Step5 布局（关联 #33，对应 `test_step5_password_hint_text_and_alignment`） | 渲染 `Step5_QMT()` | 标签宽度 `w-28`；密码框 `id="qmt-password-input"` + 复选框 `id="auto_start_qmt"` + 路径提示正确对齐 |
| TC-10-03 | 密码与复选框联动 | 勾上 `auto_start_qmt` 不填密码 → submit | `htmx:beforeRequest` 阻止 + 密码框 `input-error` 标红 |
| TC-10-04 | 错误信息 OOB 清理 | 重试时旧错误清空 | `#wizard-error` 区域被 OOB 替换为空 |
| TC-10-05 | 多浏览器（Chrome / Edge） | 完整跑 5 步 + QMT 启动 | 无 JS 报错；HTMX 表单数据正确序列化（含 `auto_start_qmt` 复选框未勾选时不提交的边界） |

### 11. 备份与恢复（对应"测试环境"第 3 条）

| 编号 | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| TC-11-01 | 备份文件命名 | 开始测试 | 备份写到 `<data_home>/backup/<UTC-timestamp>/`，含 `qmt_gateway.db`、日志目录快照、`settings.json` |
| TC-11-02 | 正常完成 | TC-1-02 / TC-1-03 走完 | 测试结束删除测试期间产生的 db / 数据，`restore` 备份 |
| TC-11-03 | 测试异常中断 | 任意时刻 `Ctrl+C` / 进程被杀 | 注册 `atexit` / `SIGINT` / `SIGTERM` handler 触发 restore；恢复后再退出 |
| TC-11-04 | 备份恢复幂等 | 多次运行同一测试 | 第 N 次运行前与第 1 次运行前的环境完全一致（DB 行数 / 资产 / 持仓） |

## 实施细节

### 配置备份和恢复

- **备份位置**：`<data_home>/backup/<UTC-timestamp>/`
- **备份内容**：
  - SQLite DB 文件（`qmt_gateway.db`），使用 `sqlite3.Connection.backup()` API 保留 WAL 完整性。
  - 当前生效的日志目录（按 `settings.log_path`）。
  - `settings` 序列化 JSON（便于跨平台对比）。
  - 任何在测试期间被 init-wizard 改写的用户文件（包含 `_wizard_data` 缓存镜像以便诊断）。
- **备份策略**：
  1. 测试启动时执行 `BACKUP_DB` → 输出到 `backup/<ts>/qmt_gateway.db`；
  2. 安装 `atexit`、`SIGINT`、`SIGTERM` handler 触发 `RESTORE_BACKUP`；
  3. 备份恢复使用 `sqlite3` 的 backup API（保持 WAL 完整）；
  4. 备份恢复后再清理新增的 `data/exports/minutes` 等下载副产物。
- **不备份内容**：QMT 安装目录、xtquant 目录（这些是机器级只读资产，不属于"用户配置数据"）。
- **失败兜底**：当 restore 自身失败时，记录原始备份路径到 `data/backup/last_failed_restore.txt`，避免自动覆盖；测试报告必须明确标记此情况。

### 测试驱动入口

- CLI 形式：`python -m qmt_gateway.e2e.init_wizard --qmt-path <path> --qmt-account <id> --qmt-password <pwd> [--keep-backup]`
- 入参透传：所有 init-wizard 表单字段都允许通过 CLI 覆盖（用于 CI 注入不同测试数据）。
- 退出码：`0` 全部通过；`1` 至少一个测试用例失败；`2` 环境前置不满足（如未安装 QMT、缺 xtquant 路径）。
- 报告：每条 TC 一行 PASS / FAIL，附带 `wizard_data` 快照、DB diff、关键日志片段。

### 与现有自动化测试的关系

- `pytest tests/test_init_wizard.py` 是 **单元 / 集成层**（使用 `TestClient` + 临时 sqlite），跑得快但无法验证真实 QMT 启动与桌面交互。
- 本端到端计划是 **系统层**：跑得慢、依赖真实 QMT 客户端、保留所有副作用（启动进程、修改机器配置），必须运行在有 QMT 安装的 Windows 上。
- 两条链路并行：CI 跑 pytest 保证回归；发布前跑 e2e 保证首次安装流程。
