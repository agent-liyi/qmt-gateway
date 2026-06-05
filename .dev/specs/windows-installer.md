# QMT Gateway Windows 安装方案

## 目标

为 QMT Gateway 提供 Windows 平台的一键安装体验：

1. 用户下载 exe 安装器，自带 Python 运行时，无需用户预装
2. 安装完成后立即启动服务，弹出浏览器运行 init-wizard
3. 可选注册开机自启动任务（非 Windows 服务）
4. 安装包与 qmt-gateway 核心功能职责分离：安装包只负责部署，运行时能力（版本更新、日志查看等）由 qmt-gateway 自身提供

## 设计原则

- **安装包职责最小化**：安装包只做解压、创建 venv、pip install、注册快捷方式和自启任务。运行时功能（版本检查、内核更新、服务管理）全部在 qmt-gateway Python 代码中实现
- **venv 优先**：使用 venv 管理依赖，保留 pip 更新能力，不使用 PyInstaller 单文件打包
- **国内网络友好**：pip 源默认使用国内镜像
- **GUI 会话兼容**：QMT Gateway 依赖 pywinauto 进行 QMT 登录自动化，必须运行在用户 GUI 会话中，因此不使用 Windows 服务

## 约束

- 仅支持 Windows（x64）
- Python 3.13 / 3.14，使用 venv
- 依赖 `pywinauto`（Windows GUI 自动化）
- xtquant 由 QMT 客户端提供，运行时动态加载，不在安装包中
- 数据存储使用 SQLite，默认 `~/.qmt-gateway`

---

## 安装器方案：NSIS + 内嵌 Python

### 思路

安装器内嵌 Python 3.13 嵌入式发行版（python-3.13.x-embed-amd64.zip，约 15MB），安装时解压到安装目录，在其上创建 venv 并 pip install 项目依赖。用户无需预装 Python，同时保留 venv 的灵活性。

### 目录结构

```
C:\Program Files\QMT Gateway\
  ├─ python\               # 内嵌 Python 3.13（仅用于创建 venv）
  │    ├─ python.exe
  │    ├─ python313.dll
  │    ├─ python313.zip
  │    └─ Lib\
  ├─ app\                  # 项目源码
  │    ├─ pyproject.toml
  │    ├─ qmt_gateway\
  │    └─ ...
  ├─ .venv\                # venv（基于内嵌 Python 创建）
  │    ├─ Scripts\
  │    │    ├─ python.exe
  │    │    ├─ pip.exe
  │    │    └─ qmt-gateway.exe   # console_script 入口
  │    └─ Lib\site-packages\
  ├─ data\                 # 数据目录（符号链接或配置指向 ~/.qmt-gateway）
  ├─ start.bat             # 前台启动（调试用，可见命令行窗口）
  ├─ start-silent.vbs      # 静默启动（开机自启用，隐藏窗口）
  └─ uninstall.bat         # 卸载脚本
```

### 安装流程

```
QMT-Gateway-Setup.exe (NSIS)
  │
  ├─ 欢迎页
  │    └─ 提示：本软件需要 QMT 交易客户端，请确保已安装
  │
  ├─ 许可协议页
  │
  ├─ 选择安装目录（默认 C:\Program Files\QMT Gateway）
  │
  ├─ 选项页
  │    ├─ ☑ 创建桌面快捷方式
  │    ├─ ☑ 开机自动启动（用户登录时）
  │    └─ ☑ 添加防火墙入站规则（允许局域网访问）
  │         └─ 提示：允许同一局域网内其他设备访问 QMT Gateway
  │
  ├─ 安装阶段（进度条）
  │    ├─ 解压内嵌 Python 3.13 到 python\
  │    ├─ 复制项目源码到 app\
  │    ├─ python\python.exe -m venv .venv
  │    ├─ .venv\Scripts\pip install -e app\  （配置国内 pip 源）
  │    ├─ 创建桌面快捷方式 → start-silent.vbs
  │    ├─ 创建开始菜单项
  │    ├─ 注册开机自启任务（schtasks /sc onlogon）
  │    └─ 添加防火墙规则（需管理员权限，用户 UAC 确认）
  │
  ├─ 完成页
  │    ├─ ☑ 立即启动 QMT Gateway
  │    └─ 点击完成 → start.bat → 浏览器打开 init-wizard
  │
  └─ 首次启动 → http://localhost:8130 → init-wizard
```

### pip 国内源配置

安装过程中 pip 使用国内镜像源，在 venv 创建后、pip install 前写入：

**`.venv\pip.conf`**（或通过命令行 `pip install -i` 指定）：

```ini
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
```

或使用其他镜像：

| 镜像 | 地址 |
|------|------|
| 清华 | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| 阿里云 | `https://mirrors.aliyun.com/pypi/simple` |
| 腾讯云 | `https://mirrors.cloud.tencent.com/pypi/simple` |

安装器默认使用清华源，可在安装选项页提供下拉选择。

### 端口冲突处理

安装器不处理端口冲突。默认使用 8130，由 qmt-gateway 启动时检测：

1. 启动时绑定 8130，若失败则依次尝试 8131、8132...8139
2. 找到可用端口后写入配置
3. 浏览器打开实际使用的端口
4. 用户可在 init-wizard 第 3 步（Server Setup）修改端口

此逻辑在 qmt-gateway Python 代码中实现（`__main__.py` 或 `runtime.py`），不属于安装包。

### 防火墙规则

安装器以管理员权限运行，在安装阶段弹出 UAC 确认后执行：

```bat
netsh advfirewall firewall add rule name="QMT Gateway" dir=in action=allow protocol=tcp localport=8130 profile=private enable=yes
```

- 仅允许 private profile（局域网），不允许 public profile
- 若用户未授权防火墙规则，安装继续但跳过此步骤
- 端口变更时，由 qmt-gateway 运行时更新规则（Python 代码实现）

### 启动脚本

**start.bat**（前台启动，调试用）：

```bat
@echo off
cd /d "%~dp0"
set "QMT_GATEWAY_HOME=%~dp0data\home"
set "PYTHONUTF8=1"
start "" "http://localhost:8130"
.venv\Scripts\python.exe -m qmt_gateway
```

**start-silent.vbs**（静默启动，开机自启用）：

```vb
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Environment("Process").Item("QMT_GATEWAY_HOME") = WshShell.CurrentDirectory & "\data\home"
WshShell.Environment("Process").Item("PYTHONUTF8") = "1"
WshShell.Run """.venv\Scripts\python.exe"" -m qmt_gateway", 0, False
```

### 开机自启

使用 Windows 任务计划程序注册"用户登录时"触发的任务：

```bat
schtasks /create /tn "QMT Gateway" /tr "wscript.exe \"%INSTALL_DIR%\start-silent.vbs\"" /sc onlogon /rl limited /f
```

- 运行在用户 GUI 会话中，pywinauto 正常工作
- 使用 limited 权限（非 highest），避免每次登录弹 UAC
- 安装器注册，卸载时删除：`schtasks /delete /tn "QMT Gateway" /f`
- 可在 init-wizard 或 Web UI 中开关此选项

### QMT 提示

安装器欢迎页显示提示文字：

> 本软件需要配合迅投 QMT 交易客户端使用。如果您尚未安装 QMT，请先前往券商官网下载安装。QMT 安装路径将在初始化向导中配置。

不主动检测 QMT 是否已安装，因为：
- QMT 安装位置不固定，检测逻辑不可靠
- 用户可能先安装 Gateway，稍后再安装 QMT
- QMT 路径在 init-wizard 第 5 步由用户指定

---

## 卸载流程

```
uninstall.bat
  │
  ├─ 停止运行中的 qmt-gateway 进程（taskkill）
  ├─ 删除任务计划：schtasks /delete /tn "QMT Gateway" /f
  ├─ 删除防火墙规则：netsh advfirewall firewall delete rule name="QMT Gateway"
  ├─ 删除桌面快捷方式
  ├─ 删除开始菜单项
  ├─ 询问是否删除数据目录（默认保留）
  └─ 删除安装目录
```

---

## 升级流程

升级由 qmt-gateway 运行时自身处理，安装包不负责版本更新。

### 内核更新机制

qmt-gateway 内建版本检查和更新能力，通过 PyPI 检查最新版本：

1. **版本检查**：
   - **每日自动检查一次**：通过 APScheduler 在后台每天调度一次查询 PyPI
   - **用户手动触发**：Web UI 提供"检查更新"按钮
   - 查询方式：`GET https://pypi.org/pypi/qmt-gateway/json` → 解析 `info.version`
   - 与当前版本比较，若有新版本则在 Web UI 显示通知（不强制升级）

2. **内核更新**：用户确认后，通过 pip 更新
   ```
   .venv\Scripts\pip install --upgrade qmt-gateway
   ```
   - 仅更新 Python 包（qmt_gateway 及其依赖），不涉及安装器、Python 运行时、启动脚本
   - 更新完成后自动重启服务
   - 更新前自动备份当前版本（保留最近 3 个版本），更新失败可回滚

3. **Web UI 入口**：
   - 版本号显示（当前版本 + 最新版本标记）
   - "检查更新"按钮（手动触发）
   - 更新日志展示
   - 更新进度条

4. **国内源**：pip 更新同样使用国内镜像源

此功能为 qmt-gateway 服务端 API + Web UI 实现，需新增：
- `GET /api/system/version` — 返回当前版本和最新版本
- `POST /api/system/update` — 执行 pip 更新并重启
- Web UI 版本通知组件

---

## 安装包与 qmt-gateway 职责划分

| 职责 | 安装包 | qmt-gateway |
|------|--------|-------------|
| 解压 Python 运行时 + 源码 | ✅ | |
| 创建 venv + pip install | ✅ | |
| 桌面快捷方式 / 开始菜单 | ✅ | |
| 注册开机自启任务 | ✅ | |
| 添加防火墙规则 | ✅ | |
| 卸载（清理安装文件） | ✅ | |
| 端口冲突检测与切换 | | ✅ |
| 防火墙规则更新（端口变更时） | | ✅ |
| 版本检查 / 内核更新 | | ✅ |
| 开机自启开关切换 | | ✅ |
| 服务启停管理 | | ✅ |
| 日志查看 | | ✅（Web UI） |
| QMT 路径配置 | | ✅（init-wizard） |

---

## 待实现清单

### 安装包（NSIS 脚本）

- [ ] NSIS 安装器脚本：欢迎页、安装目录选择、选项页
- [ ] 内嵌 Python 3.13 嵌入式发行版
- [ ] venv 创建 + pip install（国内源）
- [ ] 桌面快捷方式 + 开始菜单
- [ ] 开机自启任务注册
- [ ] 防火墙规则添加（需用户 UAC 授权）
- [ ] 卸载脚本
- [ ] CI 构建：GitHub Actions 打包 NSIS exe

### qmt-gateway（Python 代码）

- [ ] 端口冲突检测：启动时 8130 被占用则自动尝试 8131-8139
- [ ] 防火墙规则更新 API：端口变更时更新 netsh 规则
- [ ] 每日版本检查：APScheduler 每天调度一次查询 PyPI，缓存最新版本号
- [ ] 版本检查 API：`GET /api/system/version`（返回当前版本和最新版本）
- [ ] 内核更新 API：`POST /api/system/update`（pip 升级 + 重启）
- [ ] 内核回滚：保留最近 3 个版本，更新失败可回滚
- [ ] 开机自启开关 API：`POST /api/system/autostart`（切换 schtasks）
- [ ] Web UI：版本通知、更新按钮、自启开关
- [ ] pip 国内源配置持久化（写入 .venv/pip.conf）
