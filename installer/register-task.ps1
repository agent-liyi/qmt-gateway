param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)

$ErrorActionPreference = 'Stop'

$templatePath = Join-Path $InstallDir 'task-template.xml'
$taskXmlPath  = Join-Path $InstallDir 'task.xml'

$template = [IO.File]::ReadAllText($templatePath, [Text.Encoding]::UTF8)
$template = $template.Replace('@INSTDIR@', $InstallDir)

[IO.File]::WriteAllText($taskXmlPath, $template, (New-Object System.Text.UnicodeEncoding $false, $true))

& schtasks.exe /create /tn 'QMT Gateway' /xml $taskXmlPath /f
if ($LASTEXITCODE -ne 0) {
    throw "schtasks /create failed with exit code $LASTEXITCODE"
}

Remove-Item -LiteralPath $taskXmlPath -Force
