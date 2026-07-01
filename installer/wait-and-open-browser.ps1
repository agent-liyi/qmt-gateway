# 等待 gateway 写入 .port 并真正监听，然后打开浏览器。
#
# 由 start.bat 在后台调用（start "" /B powershell ... -File 本文件）。
# 单独成文件而不是内联在 start.bat 的 ^ 续行里，是因为中文系统下
# cmd.exe 用 GBK 读取 .bat，多行 ^ 续行 + 中文注释会被 GBK 字节
# 切断，导致注释内容被当作命令执行。
#
# 调用：powershell -NoProfile -ExecutionPolicy Bypass -File 本文件 -PortFile <path>
param(
    [Parameter(Mandatory = $true)]
    [string]$PortFile
)

$defaultPort = 8130

# 1. 等 gateway 写 .port（最多 15 秒）
$w = 0
while ($w -lt 15) {
    if (Test-Path -LiteralPath $PortFile) {
        $r = Get-Content -LiteralPath $PortFile -ErrorAction SilentlyContinue
        if ($r -match '^\d+$') { break }
    }
    Start-Sleep -Seconds 1
    $w++
}

# 2. 读真实端口（8130 被占用时 gateway 会跳到 8131-8139）
$port = $defaultPort
if (Test-Path -LiteralPath $PortFile) {
    $r = Get-Content -LiteralPath $PortFile -ErrorAction SilentlyContinue
    if ($r -match '^\d+$') { $port = [int]$r }
}

# 3. 探活端口就绪后打开浏览器（最多 30 秒）
$w = 0
while ($w -lt 30) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect('127.0.0.1', $port)
        $c.Close()
        Start-Process "http://localhost:$port"
        exit 0
    } catch {}
    Start-Sleep -Seconds 1
    $w++
}
exit 1
