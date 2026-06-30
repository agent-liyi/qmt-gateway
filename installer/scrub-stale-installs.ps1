<#
Clean up stale QMT Gateway install entries.

Old NSIS installers (before build 73) write uninstall info to

  HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\<DisplayName>

but do NOT clean up old entries when the user reinstalls. If the user
upgrades from one install path to another (e.g. Chinese to English
Program Files), the old UninstallString points to a missing uninstall.exe,
and clicking Uninstall in the Control Panel triggers a Windows 'is
searching for uninstall.bat' dialog.

Matching strategy: scan both Uninstall roots; for each subkey whose
NSIS:StartMenuDir equals 'qmt-gateway' (always ASCII regardless of
brand string encoding), check InstallLocation against the current
InstallDir. If they differ (or InstallLocation is missing), the entry
is stale and we remove it.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)

$ErrorActionPreference = 'SilentlyContinue'

$roots = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
)

$currentNorm = $InstallDir.TrimEnd('\').ToLowerInvariant()
$staleDirs = @()

foreach ($root in $roots) {
    if (-not (Test-Path -LiteralPath $root)) {
        continue
    }
    foreach ($sub in Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue) {
        $props = Get-ItemProperty -LiteralPath $sub.PSPath -ErrorAction SilentlyContinue
        $startMenuDir = [string]$props.'NSIS:StartMenuDir'
        # 用 ASCII 的 NSIS:StartMenuDir 匹配——无论 DisplayName 怎么 mojibake，
        # 我们的安装器永远写 'qmt-gateway'。
        if ($startMenuDir -ne 'qmt-gateway') {
            continue
        }
        $displayName = [string]$props.DisplayName
        $installLoc = [string]$props.InstallLocation
        $uninstString = [string]$props.UninstallString
        # InstallLocation 与当前 $InstallDir 一致 → 当前 entry，保留
        $locNorm = $installLoc.TrimEnd('\').ToLowerInvariant()
        if ($installLoc -and $locNorm -eq $currentNorm) {
            continue
        }
        # 别的 qmt-gateway entry（路径不一致 / 无路径 / 旧路径不存在）→ stale
        Write-Host "scrub: removing stale uninstall entry '$displayName' @ $installLoc"
        if ($installLoc) {
            $staleDirs += $installLoc
        }
        try {
            Remove-Item -LiteralPath $sub.PSPath -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Host "scrub: failed to remove registry key $($sub.PSPath): $_"
        }
    }
}

foreach ($dir in ($staleDirs | Sort-Object -Unique)) {
    if (Test-Path -LiteralPath $dir) {
        try {
            Write-Host "scrub: removing stale install dir $dir"
            Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Host "scrub: failed to remove stale install dir $dir : $_"
        }
    }
}

# 同时清掉开始菜单里残留的旧文件夹（如 qmt-gateway / mojibake '匡醍...'）
$smRoot = [Environment]::GetFolderPath('Programs')
if (Test-Path -LiteralPath $smRoot) {
    foreach ($name in @('qmt-gateway', '迅投 QMT 交易网关')) {
        $dir = Join-Path $smRoot $name
        if (Test-Path -LiteralPath $dir) {
            try {
                Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction Stop
                Write-Host "scrub: removed stale start menu folder $dir"
            } catch {
                Write-Host "scrub: failed to remove stale start menu folder $dir : $_"
            }
        }
    }
    # 清掉 mojibake 文件夹（双重 UTF-8 编码），条件：字节含 0xC2/0xC3 + 名字含 "QMT"
    Get-ChildItem -LiteralPath $smRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            $n = $_.Name
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($n)
            $hasC2C3 = ($bytes -contains 0xC2) -or ($bytes -contains 0xC3)
            $hasQMT = $n -match 'QMT'
            $hasC2C3 -and $hasQMT
        } |
        ForEach-Object {
            try {
                Write-Host "scrub: removing mojibake start menu folder $($_.FullName)"
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
            } catch {
                Write-Host "scrub: failed to remove mojibake folder $($_.FullName): $_"
            }
        }
}