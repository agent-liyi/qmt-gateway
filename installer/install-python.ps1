param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('InitLogs', 'Runtime', 'BootstrapPip', 'InstallDependencies')]
    [string]$Stage
)

$ErrorActionPreference = 'Stop'

$DiagnosticDir = 'C:\Temp'
$InstallLogName = 'install.log'
$TempInstallLog = Join-Path $DiagnosticDir 'qmt-gateway-installer.log'
$TempExtractLog = Join-Path $DiagnosticDir 'qmt-gateway-extract.log'
$TempBootstrapLog = Join-Path $DiagnosticDir 'qmt-gateway-bootstrap-pip.log'
$TempInstallDepsLog = Join-Path $DiagnosticDir 'qmt-gateway-install-deps.log'
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
    $summaryLines = @(
        '[Install]',
        ('INSTDIR=' + $InstallDir),
        ('TEMP_LOG=' + $TempInstallLog),
        ('PYTHON_DIR=' + $PythonDir),
        ('APP_DIR=' + $AppDir)
    )

    Set-Content -LiteralPath $InstallLog -Encoding UTF8 -Value $summaryLines
    Set-Content -LiteralPath $TempInstallLog -Encoding UTF8 -Value $summaryLines

    foreach ($detailLog in @(
        (Join-Path $PythonDir '_extract.log'),
        $TempExtractLog,
        (Join-Path $PythonDir '_bootstrap_pip.log'),
        $TempBootstrapLog,
        (Join-Path $PythonDir '_install_deps.log'),
        $TempInstallDepsLog
    )) {
        Set-Content -LiteralPath $detailLog -Encoding UTF8 -Value @()
    }
}

function Add-InstallerLogLine {
    param([string]$Line)

    Add-Content -LiteralPath $InstallLog -Encoding UTF8 -Value $Line
    Add-Content -LiteralPath $TempInstallLog -Encoding UTF8 -Value $Line
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
        [string]$DetailLog,
        [string]$TempDetailLog
    )

    if (-not (Test-Path -LiteralPath $OutputPath)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $OutputPath) {
        Write-Output $line
        Add-Content -LiteralPath $DetailLog -Encoding UTF8 -Value $line
        Add-Content -LiteralPath $TempDetailLog -Encoding UTF8 -Value $line
    }
}

function Invoke-LoggedPython {
    param(
        [string[]]$Arguments,
        [string]$DetailLog,
        [string]$TempDetailLog
    )

    $outputPath = Join-Path $DiagnosticDir ([System.IO.Path]::GetRandomFileName())
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $PythonExe @Arguments > $outputPath 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }

    Add-DetailOutput -OutputPath $outputPath -DetailLog $DetailLog -TempDetailLog $TempDetailLog
    Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue
    return $exitCode
}

function Invoke-RuntimeStage {
    $extractLog = Join-Path $PythonDir '_extract.log'
    $zipPath = Join-Path $PythonDir 'python-embed.zip'
    $pthPath = Join-Path $PythonDir 'python313._pth'

    Add-InstallerLogLines @(
        ('INSTDIR=' + $InstallDir),
        ('TEMP_LOG=' + $TempInstallLog),
        ('PYTHON_DIR=' + $PythonDir),
        ('APP_DIR=' + $AppDir),
        ('EXTRACT_LOG=' + $extractLog),
        ('TEMP_EXTRACT_LOG=' + $TempExtractLog)
    )

    $outputPath = Join-Path $DiagnosticDir ([System.IO.Path]::GetRandomFileName())
    Expand-Archive -Path $zipPath -DestinationPath $PythonDir -Force *> $outputPath
    Add-DetailOutput -OutputPath $outputPath -DetailLog $extractLog -TempDetailLog $TempExtractLog
    Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue

    if (Test-Path -LiteralPath $pthPath) {
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

    Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
    Add-InstallerLogLine ('REMOVED=' + $zipPath)
}

function Invoke-BootstrapPipStage {
    $bootstrapLog = Join-Path $PythonDir '_bootstrap_pip.log'
    $getPip = Join-Path $PythonDir 'get-pip.py'

    Add-InstallerLogLines @(
        'PIP_BOOTSTRAP_START',
        ('BOOTSTRAP_LOG=' + $bootstrapLog),
        ('TEMP_BOOTSTRAP_LOG=' + $TempBootstrapLog)
    )

    $exitCode = Invoke-LoggedPython -Arguments @(
        $getPip,
        '--no-warn-script-location',
        '-i',
        $PipIndexUrl,
        '--trusted-host',
        $PipTrustedHost
    ) -DetailLog $bootstrapLog -TempDetailLog $TempBootstrapLog

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
        ) -DetailLog $bootstrapLog -TempDetailLog $TempBootstrapLog
    }

    Remove-Item -LiteralPath $getPip -Force -ErrorAction SilentlyContinue
    exit $exitCode
}

function Invoke-InstallDependenciesStage {
    $installDepsLog = Join-Path $PythonDir '_install_deps.log'
    $pyprojectPath = Join-Path $AppDir 'pyproject.toml'
    $requirementsPath = Join-Path $DiagnosticDir 'qmt-gateway-requirements.txt'
    $depsScriptPath = Join-Path $DiagnosticDir 'qmt-gateway-read-deps.py'

    Add-InstallerLogLines @(
        'PIP_INSTALL_START',
        ('INSTALL_DEPS_LOG=' + $installDepsLog),
        ('TEMP_INSTALL_DEPS_LOG=' + $TempInstallDepsLog),
        ('REQUIREMENTS=' + $requirementsPath)
    )

    [System.IO.File]::WriteAllText($depsScriptPath, @'
import pathlib
import sys
import tomllib

data = tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
dependencies = data.get("project", {}).get("dependencies", [])
pathlib.Path(sys.argv[2]).write_text("\n".join(dependencies) + "\n", encoding="utf-8")
'@, [System.Text.UTF8Encoding]::new($false))

    $exitCode = Invoke-LoggedPython -Arguments @(
        $depsScriptPath,
        $pyprojectPath,
        $requirementsPath
    ) -DetailLog $installDepsLog -TempDetailLog $TempInstallDepsLog

    if ($exitCode -eq 0) {
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
        ) -DetailLog $installDepsLog -TempDetailLog $TempInstallDepsLog
    }

    exit $exitCode
}

try {
    New-Item -ItemType Directory -Path $DiagnosticDir -Force | Out-Null
    switch ($Stage) {
        'InitLogs' { Initialize-InstallerLogs }
        'Runtime' { Invoke-RuntimeStage }
        'BootstrapPip' { Invoke-BootstrapPipStage }
        'InstallDependencies' { Invoke-InstallDependenciesStage }
    }
} catch {
    Add-InstallerLogLine ('ERROR: ' + $_.Exception.Message)
    Write-Error $_
    exit 1
}