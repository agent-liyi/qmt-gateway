param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('InitLogs', 'Runtime', 'BootstrapPip', 'InstallDependencies', 'WaitForBrowser')]
    [string]$Stage
)

$ErrorActionPreference = 'Stop'

$InstallLogName = 'install.log'
$PipIndexUrl = 'https://pypi.tuna.tsinghua.edu.cn/simple'
$PipTrustedHost = 'pypi.tuna.tsinghua.edu.cn'
$StateRegistryPaths = @(
    'HKLM:\SOFTWARE\qmt-gateway',
    'HKLM:\SOFTWARE\WOW6432Node\qmt-gateway'
)

function Get-InstallLocation {
    foreach ($path in $StateRegistryPaths) {
        try {
            $value = (Get-ItemProperty -LiteralPath $path -ErrorAction Stop).InstallLocation
            if ($value) {
                return $value
            }
        } catch {
        }
    }

    throw 'InstallLocation registry value was not found'
}

$InstallDir = Get-InstallLocation
$PythonDir = Join-Path $InstallDir 'python'
$AppDir = Join-Path $InstallDir 'app'
$InstallLog = Join-Path $InstallDir $InstallLogName
$PythonExe = Join-Path $PythonDir 'python.exe'

function Initialize-InstallerLogs {
    foreach ($directory in @($InstallDir, $PythonDir, $AppDir)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $summaryLines = @(
        '[Install]',
        ('INSTDIR=' + $InstallDir),
        ('PYTHON_DIR=' + $PythonDir),
        ('APP_DIR=' + $AppDir)
    )

    Set-Content -LiteralPath $InstallLog -Encoding UTF8 -Value $summaryLines

    foreach ($detailLog in @(
        (Join-Path $PythonDir '_extract.log'),
        (Join-Path $PythonDir '_bootstrap_pip.log'),
        (Join-Path $PythonDir '_install_deps.log')
    )) {
        Set-Content -LiteralPath $detailLog -Encoding UTF8 -Value @()
    }
}

function Add-InstallerLogLine {
    param([string]$Line)

    Add-Content -LiteralPath $InstallLog -Encoding UTF8 -Value $Line
}

function Add-InstallerLogLines {
    param([string[]]$Lines)

    foreach ($line in $Lines) {
        Add-InstallerLogLine $line
    }
}

function Add-DetailOutput {
    param(
        [string]$OutputPath,
        [string]$DetailLog
    )

    if (-not (Test-Path -LiteralPath $OutputPath)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $OutputPath) {
        Write-Output $line
        Add-Content -LiteralPath $DetailLog -Encoding UTF8 -Value $line
    }
}

function Invoke-LoggedPython {
    param(
        [string[]]$Arguments,
        [string]$DetailLog
    )

    $outputPath = Join-Path $PythonDir ([System.IO.Path]::GetRandomFileName())
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $PythonExe @Arguments > $outputPath 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }

    Add-DetailOutput -OutputPath $outputPath -DetailLog $DetailLog
    Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue
    return $exitCode
}

function Invoke-RuntimeStage {
    # The NSIS installer extracts python-embed.zip via the built-in
    # ZipDLL plugin before invoking this stage. This stage only patches
    # python313._pth so the embedded interpreter can import pip and our
    # application package.
    $extractLog = Join-Path $PythonDir '_extract.log'
    $pthPath = Join-Path $PythonDir 'python313._pth'

    Add-InstallerLogLines @(
        ('INSTDIR=' + $InstallDir),
        ('PYTHON_DIR=' + $PythonDir),
        ('APP_DIR=' + $AppDir),
        ('EXTRACT_LOG=' + $extractLog)
    )

    if (-not (Test-Path -LiteralPath $pthPath)) {
        Add-InstallerLogLine ('ERROR: missing python313._pth at ' + $pthPath)
        throw "python313._pth was not produced by the installer; python-embed.zip extraction likely failed"
    }

    $pthLines = [System.Collections.Generic.List[string]]::new()
    $hasSitePackages = $false
    $hasAppDir = $false

    foreach ($line in Get-Content -LiteralPath $pthPath) {
        switch ($line) {
            'Lib\site-packages' {
                $hasSitePackages = $true
                $pthLines.Add($line)
                continue
            }
            '..\app' {
                $hasAppDir = $true
                $pthLines.Add($line)
                continue
            }
            'import site' { continue }
            '#import site' { continue }
            default {
                $pthLines.Add($line)
            }
        }
    }

    if (-not $hasSitePackages) {
        $pthLines.Add('Lib\site-packages')
    }
    if (-not $hasAppDir) {
        $pthLines.Add('..\app')
    }
    $pthLines.Add('import site')

    $content = [string]::Join("`r`n", $pthLines) + "`r`n"
    [System.IO.File]::WriteAllText($pthPath, $content, [System.Text.UTF8Encoding]::new($false))
    Add-InstallerLogLine ('UPDATED_PTH=' + $pthPath)
}

function Invoke-BootstrapPipStage {
    $bootstrapLog = Join-Path $PythonDir '_bootstrap_pip.log'
    $getPip = Join-Path $PythonDir 'get-pip.py'

    Add-InstallerLogLines @(
        'PIP_BOOTSTRAP_START',
        ('BOOTSTRAP_LOG=' + $bootstrapLog)
    )

    $exitCode = Invoke-LoggedPython -Arguments @(
        $getPip,
        '--no-warn-script-location',
        '-i',
        $PipIndexUrl,
        '--trusted-host',
        $PipTrustedHost
    ) -DetailLog $bootstrapLog

    if ($exitCode -eq 0) {
        $exitCode = Invoke-LoggedPython -Arguments @(
            '-m',
            'pip',
            'install',
            'setuptools>=68',
            'wheel',
            '--no-warn-script-location',
            '-i',
            $PipIndexUrl,
            '--trusted-host',
            $PipTrustedHost
        ) -DetailLog $bootstrapLog
    }

    Remove-Item -LiteralPath $getPip -Force -ErrorAction SilentlyContinue
    exit $exitCode
}

function Invoke-InstallDependenciesStage {
    $installDepsLog = Join-Path $PythonDir '_install_deps.log'
    $requirementsPath = Join-Path $AppDir 'requirements.txt'

    Add-InstallerLogLines @(
        'PIP_INSTALL_START',
        ('INSTALL_DEPS_LOG=' + $installDepsLog),
        ('REQUIREMENTS=' + $requirementsPath)
    )

    $exitCode = Invoke-LoggedPython -Arguments @(
        '-m',
        'pip',
        'install',
        '-r',
        $requirementsPath,
        '--no-warn-script-location',
        '-i',
        $PipIndexUrl,
        '--trusted-host',
        $PipTrustedHost
    ) -DetailLog $installDepsLog

    exit $exitCode
}

function Invoke-WaitForBrowserStage {
    # 等待 gateway 写入 data\home\.port（实际监听端口），然后探活并打开浏览器。
    # 8130 被占用时 gateway 会自动跳到 8131-8139；如果继续打开 8130，
    # 用户就会看到"无法连接"。所以必须从 .port 读真实端口。
    $portFile = Join-Path $InstallDir 'data\home\.port'
    $defaultPort = 8130
    $port = $defaultPort

    Add-InstallerLogLines @(
        'WAIT_FOR_BROWSER_START',
        ('PORT_FILE=' + $portFile)
    )

    $waited = 0
    while ($waited -lt 15) {
        if (Test-Path -LiteralPath $portFile) {
            $raw = Get-Content -LiteralPath $portFile -ErrorAction SilentlyContinue
            if ($raw -and $raw -match '^\d+$') {
                $port = [int]$raw
                Add-InstallerLogLine ('PORT_FILE_READ=' + $port)
                break
            }
        }
        Start-Sleep -Seconds 1
        $waited++
    }

    if ($port -eq $defaultPort) {
        Add-InstallerLogLine 'PORT_FILE_NOT_FOUND_FALLBACK=8130'
    }

    $ready = $false
    $waited = 0
    while ($waited -lt 30) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient('localhost', $port)
            $client.Close()
            $ready = $true
            break
        } catch {
            Start-Sleep -Seconds 1
            $waited++
        }
    }

    if ($ready) {
        $url = 'http://localhost:' + $port
        Add-InstallerLogLine ('BROWSER_OPEN=' + $url)
        Start-Process $url
    } else {
        Add-InstallerLogLine 'BROWSER_OPEN_SKIPPED=gateway_not_ready'
    }
}

try {
    switch ($Stage) {
        'InitLogs' { Initialize-InstallerLogs }
        'Runtime' { Invoke-RuntimeStage }
        'BootstrapPip' { Invoke-BootstrapPipStage }
        'InstallDependencies' { Invoke-InstallDependenciesStage }
        'WaitForBrowser' { Invoke-WaitForBrowserStage }
    }
} catch {
    Add-InstallerLogLine ('ERROR: ' + $_.Exception.Message)
    Write-Error $_
    exit 1
}