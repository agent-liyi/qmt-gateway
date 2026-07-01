"""杀进程 helper：只杀 QMT Gateway 相关的 python.exe。

由 installer.nsi 在 .onInit 阶段调用，避免 tar -xf 解压 python-embed.zip
时遇到被进程持有的 .pyd/.dll 报 "Can't unlink already-existing object"
并段错误退出（HEAP_CORRUPTION -1073740940）。

精确匹配：CommandLine 含 "qmt_gateway" 或 "quantide-gateway"（install
路径）——不动用户的其它 Python IDE / 脚本 / notebook / jupyter 等。
"""
$ErrorActionPreference = 'SilentlyContinue'

$pidsToKill = @()
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
    $cmd = [string]$_.CommandLine
    if ($cmd -match 'qmt_gateway|quantide-gateway') {
        $pidsToKill += $_.ProcessId
    }
}

foreach ($pid in $pidsToKill) {
    try {
        Stop-Process -Id $pid -Force -ErrorAction Stop
    } catch {
        # 进程可能在我们检查后退出；忽略
    }
}

# 等 2 秒让 Windows 释放文件句柄
Start-Sleep -Seconds 2
exit 0