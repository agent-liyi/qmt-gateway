# 用 WScript.Shell 创建 Unicode 快捷方式。
#
# NSIS 自带的 CreateShortCut 即便在 Unicode 模式下，写出的 .lnk 文件名
# 也只能落到系统 ANSI 代码页。中文系统下 Start Menu / Desktop 上会
# 显示成 "e¿...æŠ• QMT äº¤æ˜"ç½"å..." 这种乱码。本脚本通过 COM
# IShellLinkW 写 UTF-16 LE 名称，Windows 资源管理器能正确解码。
#
# 调用：
#   powershell -NoProfile -ExecutionPolicy Bypass -File create-shortcuts.ps1 `
#       -InstallDir "C:\Program Files\quantide-gateway" `
#       -StartMenuDir "匡醍 QMT 交易网关" `
#       -Actions @("Start","Stop","Uninstall","Website") `
#       -WebsiteUrl "https://github.com/zillionare/qmt-gateway"
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,

    [Parameter(Mandatory = $true)]
    [string]$StartMenuDir,

    [string[]]$Actions = @('Start', 'Uninstall', 'Website'),

    [string]$WebsiteUrl = 'https://blog.quantide.cn',

    [string]$AppName = '匡醍 QMT 交易网关'
)

$ErrorActionPreference = 'Stop'

# 所有需要创建快捷方式的位置：开始菜单 + 桌面
$shell = New-Object -ComObject WScript.Shell

function New-Shortcut {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Target,
        [string]$Arguments = '',
        [string]$WorkingDirectory = '',
        [string]$IconLocation = '',
        [string]$Description = ''
    )
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    if ($Arguments)      { $shortcut.Arguments = $Arguments }
    if ($WorkingDirectory) { $shortcut.WorkingDirectory = $WorkingDirectory }
    if ($IconLocation)  { $shortcut.IconLocation = $IconLocation }
    if ($Description)   { $shortcut.Description = $Description }
    # WindowStyle 7 = minimized, 3 = maximized, 1 = normal
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}

function Remove-Shortcut {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
}

# Start Menu 目录
$startMenuRoot = [Environment]::GetFolderPath('Programs')
$smAppDir = Join-Path $startMenuRoot $StartMenuDir

# Desktop 目录
$desktopRoot = [Environment]::GetFolderPath('Desktop')

# 清理可能存在的旧乱码快捷方式（重装场景）
# 匹配规则：
#   1. 文件名含 QMT（英文）
#   2. 文件名含 "交易" 等中文
#   3. 文件名匹配老/新命名（qmt-gateway / 匡醍 / Uninstall / Website）
# mojibake 的 .lnk 文件名（"匡醍" UTF-8 字节被当 GBK 解码后的乱码）
# 也被 qmt-gateway / QMT / 交易 之一命中，不需要单独处理
Get-ChildItem -LiteralPath $startMenuRoot -Filter '*.lnk' -ErrorAction SilentlyContinue |
    Where-Object {
        $n = $_.Name
        $n -match 'qmt-gateway' -or `
        $n -match 'QMT' -or `
        $n -match '交易' -or `
        $n -match '匡醍' -or `
        $n -match 'Uninstall' -or `
        $n -match 'Website'
    } |
    ForEach-Object {
        try {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
            Write-Host "Cleaned stale shortcut: $($_.FullName)"
        } catch {
            Write-Warning "Failed to remove $($_.FullName): $_"
        }
    }

# 同时清掉旧版留下的"qmt-gateway" / 中文名空目录（含死链的目录本身要删）
# 也清掉双重编码的 mojibake 目录——UTF-8 字节被再次 UTF-8 编码后会变成
# 'C3 A8 C2 BF ...' 这种模式，文件名校验逻辑里硬编码这个 hex 模式匹配。
foreach ($stale_dir_name in @('qmt-gateway', '匡醍 QMT 交易网关', '迅投 QMT 交易网关')) {
    $stale_dir = Join-Path $startMenuRoot $stale_dir_name
    if (Test-Path -LiteralPath $stale_dir) {
        try {
            $resolved = (Resolve-Path -LiteralPath $stale_dir).Path
            $target = (Resolve-Path -LiteralPath $smAppDir -ErrorAction SilentlyContinue)
            if (-not $target -or $resolved -ne $target.Path) {
                Remove-Item -LiteralPath $stale_dir -Recurse -Force -ErrorAction Stop
                Write-Host "Cleaned stale start menu folder: $stale_dir"
            }
        } catch {
            Write-Warning "Failed to remove stale folder $stale_dir : $_"
        }
    }
}

# 清掉双重 UTF-8 编码的 mojibake 目录。判定标准：
#   文件名含 QMT 字符串 + 文件名字节同时含 0xC2/0xC3（UTF-8 双字节前缀）
#   典型输出就是 '匡醍' 被错误地当作 ASCII 再编码一次的结果
Get-ChildItem -LiteralPath $startMenuRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object {
        $n = $_.Name
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($n)
        $has_c2_c3 = ($bytes -contains 0xC2) -or ($bytes -contains 0xC3)
        $has_qmt = $n -match 'QMT'
        $has_qmt -and $has_c2_c3
    } |
    ForEach-Object {
        try {
            $target = (Resolve-Path -LiteralPath $smAppDir -ErrorAction SilentlyContinue)
            if (-not $target -or $_.FullName -ne $target.Path) {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
                Write-Host "Cleaned mojibake start menu folder: $($_.FullName)"
            }
        } catch {
            Write-Warning "Failed to remove mojibake folder $($_.FullName): $_"
        }
    }

Get-ChildItem -LiteralPath $desktopRoot -Filter '*.lnk' -ErrorAction SilentlyContinue |
    Where-Object {
        $n = $_.Name
        $n -match 'qmt-gateway' -or `
        $n -match 'QMT' -or `
        $n -match '交易' -or `
        $n -match '匡醍'
    } |
    ForEach-Object {
        try {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
            Write-Host "Cleaned stale desktop shortcut: $($_.FullName)"
        } catch {
            Write-Warning "Failed to remove $($_.FullName): $_"
        }
    }

# 1. 启动：静默拉起 gateway + 托盘 + 打开浏览器
# 用 start-silent.vbs（和开机自启一样的路径），不弹控制台窗口——
# 用户关掉资源管理器窗口或锁屏都不会杀掉 gateway。
# start.bat 保留给开发者调试（需要看日志时手动跑）。
if ($Actions -contains 'Start') {
    $startSilentVbs = Join-Path $InstallDir 'start-silent.vbs'
    New-Shortcut `
        -Path (Join-Path $smAppDir "$AppName.lnk") `
        -Target $startSilentVbs `
        -WorkingDirectory $InstallDir `
        -Description '启动 QMT 交易网关（静默）'
    New-Shortcut `
        -Path (Join-Path $desktopRoot "$AppName.lnk") `
        -Target $startSilentVbs `
        -WorkingDirectory $InstallDir `
        -Description '启动 QMT 交易网关（静默）'
}

# 2. 卸载：托盘菜单接管了"停止"/"重启"，开始菜单不再列停止入口
# NSIS 的 WriteUninstaller 生成的是 uninstall.exe（见 installer.nsi -Post
# 段），而不是 uninstall.bat。早期版本误指向 uninstall.bat，导致开始菜单
# 的 Uninstall.lnk 点击后提示找不到文件（控制面板走的是注册表
# UninstallString，指向 uninstall.exe，所以控制面板卸载正常）。
if ($Actions -contains 'Uninstall') {
    New-Shortcut `
        -Path (Join-Path $smAppDir '卸载.lnk') `
        -Target (Join-Path $InstallDir 'uninstall.exe') `
        -WorkingDirectory $InstallDir `
        -Description '卸载 QMT Gateway'
    New-Shortcut `
        -Path (Join-Path $smAppDir 'Uninstall.lnk') `
        -Target (Join-Path $InstallDir 'uninstall.exe') `
        -WorkingDirectory $InstallDir `
        -Description 'Uninstall QMT Gateway'
}

# 3. Website
if ($Actions -contains 'Website') {
    $urlFile = Join-Path $InstallDir "$AppName.url"
    Set-Content -LiteralPath $urlFile -Value "[InternetShortcut]`r`nURL=$WebsiteUrl" -Encoding ASCII
    New-Shortcut `
        -Path (Join-Path $smAppDir 'Website.lnk') `
        -Target $urlFile `
        -WorkingDirectory $InstallDir `
        -Description '访问 QMT Gateway 项目主页'
}