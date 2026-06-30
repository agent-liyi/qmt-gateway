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

    [string]$WebsiteUrl = 'https://github.com/zillionare/qmt-gateway',

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
Get-ChildItem -LiteralPath $startMenuRoot -Filter '*.lnk' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'QMT' -or $_.Name -match 'æŠ•' -or $_.Name -match '交易' } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }
Get-ChildItem -LiteralPath $desktopRoot -Filter '*.lnk' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'QMT' -or $_.Name -match 'æŠ•' -or $_.Name -match '交易' } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }

# 1. 启动：打开浏览器（带端口探测）
if ($Actions -contains 'Start') {
    $startBat = Join-Path $InstallDir 'start.bat'
    New-Shortcut `
        -Path (Join-Path $smAppDir "$AppName.lnk") `
        -Target $startBat `
        -WorkingDirectory $InstallDir `
        -Description '打开 QMT 交易网关管理界面'
    New-Shortcut `
        -Path (Join-Path $desktopRoot "$AppName.lnk") `
        -Target $startBat `
        -WorkingDirectory $InstallDir `
        -Description '打开 QMT 交易网关管理界面'
}

# 2. 卸载：托盘菜单接管了"停止"/"重启"，开始菜单不再列停止入口
if ($Actions -contains 'Uninstall') {
    New-Shortcut `
        -Path (Join-Path $smAppDir '卸载.lnk') `
        -Target (Join-Path $InstallDir 'uninstall.bat') `
        -WorkingDirectory $InstallDir `
        -Description '卸载 QMT Gateway'
    New-Shortcut `
        -Path (Join-Path $smAppDir 'Uninstall.lnk') `
        -Target (Join-Path $InstallDir 'uninstall.bat') `
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