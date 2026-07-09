$ErrorActionPreference = 'Stop'

$Package = 'justdocs'
$Repository = if ($env:JUSTDOCS_REPOSITORY) { $env:JUSTDOCS_REPOSITORY } else { 'FanaticPythoner/justdocs' }
$Source = if ($env:JUSTDOCS_INSTALL_SOURCE) { $env:JUSTDOCS_INSTALL_SOURCE } else { 'github' }
$Version = if ($env:JUSTDOCS_INSTALL_VERSION) { $env:JUSTDOCS_INSTALL_VERSION } else { '' }
$Ref = if ($env:JUSTDOCS_INSTALL_REF) { $env:JUSTDOCS_INSTALL_REF } else { 'main' }
$Spec = if ($env:JUSTDOCS_INSTALL_SPEC) { $env:JUSTDOCS_INSTALL_SPEC } else { '' }
$DryRun = if ($env:JUSTDOCS_INSTALL_DRY_RUN) { $env:JUSTDOCS_INSTALL_DRY_RUN } else { '0' }

function Resolve-JustdocsPython {
    if ($env:JUSTDOCS_PYTHON) {
        return @($env:JUSTDOCS_PYTHON)
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @('py', '-3')
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @('python')
    }
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        return @('python3')
    }
    throw 'Python 3.10+ is required.'
}

function Invoke-JustdocsPython {
    param([string[]]$Arguments)

    $Executable = $script:PythonCommand[0]
    $Prefix = @()
    if ($script:PythonCommand.Count -gt 1) {
        $Prefix = $script:PythonCommand[1..($script:PythonCommand.Count - 1)]
    }
    & $Executable @Prefix @Arguments
}

$script:PythonCommand = Resolve-JustdocsPython

Invoke-JustdocsPython @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)')
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.10+ is required.'
}

if (-not $Spec) {
    switch ($Source) {
        'pypi' {
            if ($Version) {
                $Spec = "$Package==$Version"
            } else {
                $Spec = $Package
            }
        }
        'github' {
            $Spec = "https://github.com/$Repository/archive/$Ref.tar.gz"
        }
        'url' {
            if (-not $env:JUSTDOCS_INSTALL_URL) {
                throw 'JUSTDOCS_INSTALL_URL must be set.'
            }
            $Spec = $env:JUSTDOCS_INSTALL_URL
        }
        default {
            throw "unsupported JUSTDOCS_INSTALL_SOURCE '$Source': expected pypi, github, or url"
        }
    }
}

if ($DryRun -in @('1', 'true', 'TRUE', 'yes', 'YES')) {
    Write-Output (($script:PythonCommand + @('-m', 'pip', 'install', '--user', '--upgrade', $Spec)) -join ' ')
    return
}

Invoke-JustdocsPython @('-m', 'pip', '--version')
if ($LASTEXITCODE -ne 0) {
    Invoke-JustdocsPython @('-m', 'ensurepip', '--user')
}

Invoke-JustdocsPython @('-m', 'pip', 'install', '--user', '--upgrade', $Spec)

$ScriptsDir = Invoke-JustdocsPython @('-c', 'import os, sysconfig; print(sysconfig.get_path("scripts", scheme=f"{os.name}_user") or "")')
if (-not $ScriptsDir) {
    throw 'Python user scripts directory is unavailable.'
}

$Command = Get-Command justdocs -ErrorAction SilentlyContinue
if (-not $Command) {
    throw "justdocs install completed, but the command is not on PATH. Add Python user scripts directory to PATH: $ScriptsDir"
}

if (-not $Command.Source.StartsWith($ScriptsDir, [StringComparison]::OrdinalIgnoreCase)) {
    throw "justdocs resolves outside Python user scripts: $($Command.Source). Expected scripts directory: $ScriptsDir"
}

Write-Output "installed $($Command.Source)"
justdocs version
