$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Package = 'justdocs'
$Repository = if ($env:JUSTDOCS_REPOSITORY) { $env:JUSTDOCS_REPOSITORY } else { 'FanaticPythoner/justdocs' }
$Source = if ($env:JUSTDOCS_INSTALL_SOURCE) { $env:JUSTDOCS_INSTALL_SOURCE } else { 'github' }
$Version = if ($env:JUSTDOCS_INSTALL_VERSION) { $env:JUSTDOCS_INSTALL_VERSION } else { '' }
$Ref = if ($env:JUSTDOCS_INSTALL_REF) { $env:JUSTDOCS_INSTALL_REF } else { '' }
$Spec = if ($env:JUSTDOCS_INSTALL_SPEC) { $env:JUSTDOCS_INSTALL_SPEC } else { '' }
$Action = if ($env:JUSTDOCS_INSTALL_ACTION) { $env:JUSTDOCS_INSTALL_ACTION } else { 'install' }
$DryRun = if ($env:JUSTDOCS_INSTALL_DRY_RUN) { $env:JUSTDOCS_INSTALL_DRY_RUN } else { '0' }
$ModifyPath = if ($env:JUSTDOCS_MODIFY_PATH) { $env:JUSTDOCS_MODIFY_PATH } else { '1' }
$Timeout = if ($env:JUSTDOCS_INSTALL_TIMEOUT) { $env:JUSTDOCS_INSTALL_TIMEOUT } else { '10' }
$LocalAppData = [Environment]::GetFolderPath('LocalApplicationData')
$ConfiguredInstallRoot = if ($env:JUSTDOCS_INSTALL_ROOT) { $env:JUSTDOCS_INSTALL_ROOT } else { Join-Path $LocalAppData 'justdocs' }
$InstallRoot = [IO.Path]::GetFullPath($ConfiguredInstallRoot)
$BinDir = Join-Path $InstallRoot 'bin'
$VenvDir = Join-Path $InstallRoot 'venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvCommand = Join-Path $VenvDir 'Scripts\justdocs.exe'
$CommandPath = Join-Path $BinDir 'justdocs.exe'
$ManagedFile = Join-Path $InstallRoot '.justdocs-managed'
$LockPath = "$InstallRoot.install-lock"

function Test-JustdocsTrue {
    param([string]$Value)

    return $Value -in @('1', 'true', 'TRUE', 'yes', 'YES')
}

function Assert-JustdocsBoolean {
    param([string]$Name, [string]$Value)

    if ($Value -notin @('0', 'false', 'FALSE', 'no', 'NO', '1', 'true', 'TRUE', 'yes', 'YES')) {
        throw "invalid $Name '$Value': expected 0, 1, false, true, no, or yes"
    }
}

function Assert-JustdocsInstallRoot {
    $RootPath = [IO.Path]::GetPathRoot($InstallRoot)
    $UserProfile = [IO.Path]::GetFullPath([Environment]::GetFolderPath('UserProfile'))
    if ($InstallRoot.Equals($RootPath, [StringComparison]::OrdinalIgnoreCase) -or
        $InstallRoot.Equals($UserProfile, [StringComparison]::OrdinalIgnoreCase)) {
        throw "unsafe JUSTDOCS_INSTALL_ROOT: $InstallRoot"
    }
    if (Test-Path -LiteralPath $InstallRoot) {
        $RootItem = Get-Item -LiteralPath $InstallRoot -Force
        if (($RootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "install root cannot be a reparse point: $InstallRoot"
        }
    }
}

function Assert-JustdocsMarker {
    if (Test-Path -LiteralPath $ManagedFile) {
        $MarkerItem = Get-Item -LiteralPath $ManagedFile -Force
        if (($MarkerItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "invalid install ownership marker reparse point: $ManagedFile"
        }
    }
}

function Resolve-JustdocsPython {
    if ($env:JUSTDOCS_PYTHON) {
        return @($env:JUSTDOCS_PYTHON)
    }
    if (Get-Command py -ErrorAction Ignore) {
        return @('py', '-3')
    }
    if (Get-Command python -ErrorAction Ignore) {
        return @('python')
    }
    if (Get-Command python3 -ErrorAction Ignore) {
        return @('python3')
    }
    throw 'Python 3.10+ is required.'
}

function Invoke-JustdocsPython {
    param([string[]]$Arguments)

    $Executable = $script:PythonCommand[0]
    $Prefix = @($script:PythonCommand | Select-Object -Skip 1)
    & $Executable @Prefix @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

function Resolve-JustdocsSpec {
    if (-not $script:Spec) {
        switch ($script:Source) {
            'pypi' {
                $script:Spec = if ($script:Version) { "$Package==$($script:Version)" } else { $Package }
            }
            'github' {
                if (-not $script:Ref) {
                    $Resolver = @'
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request

repository, raw_timeout, package = sys.argv[1:]
if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
    raise SystemExit(f"invalid JUSTDOCS_REPOSITORY: {repository}")
try:
    timeout = float(raw_timeout)
except ValueError as error:
    raise SystemExit(f"invalid JUSTDOCS_INSTALL_TIMEOUT: {raw_timeout}") from error
if not math.isfinite(timeout) or timeout <= 0:
    raise SystemExit(f"invalid JUSTDOCS_INSTALL_TIMEOUT: {raw_timeout}")
headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "justdocs-installer",
    "X-GitHub-Api-Version": "2022-11-28",
}
token = os.environ.get("GITHUB_TOKEN")
if token:
    headers["Authorization"] = f"Bearer {token}"
url = f"https://api.github.com/repos/{repository}/releases/latest"
request = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
except (TimeoutError, urllib.error.URLError, OSError) as error:
    raise SystemExit(f"GitHub release lookup failed: {error}") from error
if len(payload) > 2 * 1024 * 1024:
    raise SystemExit("GitHub release lookup failed: response exceeds 2097152 bytes")
try:
    metadata = json.loads(payload.decode("utf-8"))
except (UnicodeDecodeError, json.JSONDecodeError) as error:
    raise SystemExit("GitHub release lookup failed: invalid JSON response") from error
tag = metadata.get("tag_name") if isinstance(metadata, dict) else None
if not isinstance(tag, str) or not tag or any(character.isspace() for character in tag):
    raise SystemExit("GitHub release lookup failed: tag_name missing or invalid")
assets = metadata.get("assets")
if not isinstance(assets, list):
    raise SystemExit("GitHub release lookup failed: assets list missing")
matches = [
    asset.get("browser_download_url")
    for asset in assets
    if isinstance(asset, dict)
    and isinstance(asset.get("name"), str)
    and asset["name"].startswith(f"{package}-")
    and asset["name"].endswith("-py3-none-any.whl")
    and isinstance(asset.get("browser_download_url"), str)
    and asset["browser_download_url"].endswith(f"/{asset['name']}")
]
if len(matches) != 1 or not matches[0].startswith("https://github.com/"):
    raise SystemExit("GitHub release lookup failed: expected one universal wheel asset")
print(matches[0])
'@
                    $script:Spec = (
                        Invoke-JustdocsPython @('-c', $Resolver, $Repository, $Timeout, $Package)
                    ).Trim()
                } else {
                    $script:Spec = "https://github.com/$Repository/archive/$Ref.tar.gz"
                }
            }
            'url' {
                if (-not $env:JUSTDOCS_INSTALL_URL) {
                    throw 'JUSTDOCS_INSTALL_URL must be set.'
                }
                $script:Spec = $env:JUSTDOCS_INSTALL_URL
            }
            default { throw "unsupported JUSTDOCS_INSTALL_SOURCE '$Source': expected pypi, github, or url" }
        }
    }
    if ($script:Spec.StartsWith('-')) {
        throw "invalid JUSTDOCS_INSTALL_SPEC: pip option rejected: $($script:Spec)"
    }
}

function Set-JustdocsPath {
    param([ValidateSet('Add', 'Remove')][string]$Mode)

    $Current = [Environment]::GetEnvironmentVariable('Path', 'User')
    $Parts = @($Current -split ';' | Where-Object { $_ -and -not $_.Equals($BinDir, [StringComparison]::OrdinalIgnoreCase) })
    if ($Mode -eq 'Add') {
        $Parts = @($BinDir) + $Parts
        if (-not (($env:Path -split ';') | Where-Object { $_.Equals($BinDir, [StringComparison]::OrdinalIgnoreCase) })) {
            $env:Path = "$BinDir;$env:Path"
        }
    }
    [Environment]::SetEnvironmentVariable('Path', ($Parts -join ';'), 'User')
}

function Enter-JustdocsLock {
    $Parent = Split-Path -Parent $InstallRoot
    [Directory]::CreateDirectory($Parent) | Out-Null
    try {
        $script:Lock = [IO.File]::Open($LockPath, 'CreateNew', 'Write', 'None')
    }
    catch [IO.IOException] {
        try {
            $StaleLock = [IO.File]::Open($LockPath, 'Open', 'ReadWrite', 'None')
            $StaleLock.Dispose()
            Remove-Item -LiteralPath $LockPath -Force
            $script:Lock = [IO.File]::Open($LockPath, 'CreateNew', 'Write', 'None')
        }
        catch [IO.IOException] {
            throw "justdocs installer lock is held: $LockPath"
        }
    }
}

function Claim-JustdocsInstallRoot {
    if ((Test-Path -LiteralPath $InstallRoot) -and -not (Test-Path -LiteralPath $InstallRoot -PathType Container)) {
        throw "install root is not a directory: $InstallRoot"
    }
    if (Test-Path -LiteralPath $InstallRoot -PathType Container) {
        $Entries = @(Get-ChildItem -LiteralPath $InstallRoot -Force)
        if ($Entries.Count -gt 0 -and -not (Test-Path -LiteralPath $ManagedFile -PathType Leaf)) {
            throw "refusing to use unmanaged nonempty install root: $InstallRoot"
        }
    }
    [Directory]::CreateDirectory($InstallRoot) | Out-Null
    Assert-JustdocsMarker
    if (Test-Path -LiteralPath $ManagedFile -PathType Leaf) {
        $Marker = Get-Content -LiteralPath $ManagedFile -Raw
        if ($Marker.Trim() -ne 'justdocs-managed-v1') {
            throw "invalid install ownership marker: $ManagedFile"
        }
    }
    Set-Content -LiteralPath $ManagedFile -Value 'justdocs-managed-v1' -Encoding Ascii
}

function Assert-JustdocsOwnedCommand {
    if (-not (Test-Path -LiteralPath $CommandPath -PathType Leaf)) {
        return
    }
    if (-not (Test-Path -LiteralPath $VenvCommand -PathType Leaf)) {
        throw "refusing to modify unowned command: $CommandPath"
    }
    $CommandHash = (Get-FileHash -LiteralPath $CommandPath -Algorithm SHA256).Hash
    $VenvHash = (Get-FileHash -LiteralPath $VenvCommand -Algorithm SHA256).Hash
    if ($CommandHash -ne $VenvHash) {
        throw "refusing to modify unowned command: $CommandPath"
    }
}

function Exit-JustdocsLock {
    if ($script:Lock) {
        $script:Lock.Dispose()
        $script:Lock = $null
    }
    Remove-Item -LiteralPath $LockPath -Force
}

function Install-Justdocs {
    Resolve-JustdocsSpec
    if (Test-JustdocsTrue $DryRun) {
        Write-Output (($script:PythonCommand + @('-m', 'venv', $VenvDir)) -join ' ')
        Write-Output "$VenvPython -m pip install --upgrade $Spec"
        Write-Output "copy $VenvCommand to $CommandPath"
        if (Test-JustdocsTrue $ModifyPath) {
            Write-Output "add $BinDir to the user PATH"
        }
        return
    }
    Enter-JustdocsLock
    try {
        Claim-JustdocsInstallRoot
        [Directory]::CreateDirectory($BinDir) | Out-Null
        Assert-JustdocsOwnedCommand
        if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
            Invoke-JustdocsPython @('-m', 'venv', $VenvDir)
        }
        & $VenvPython -m pip install --upgrade $Spec
        if ($LASTEXITCODE -ne 0) {
            throw "pip install failed with exit code $LASTEXITCODE."
        }
        if (-not (Test-Path -LiteralPath $VenvCommand -PathType Leaf)) {
            throw "installed package missing console command: $VenvCommand"
        }
        $TemporaryCommand = "$CommandPath.tmp.$PID"
        Copy-Item -LiteralPath $VenvCommand -Destination $TemporaryCommand -Force
        Move-Item -LiteralPath $TemporaryCommand -Destination $CommandPath -Force
        & $CommandPath version | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "installed command failed with exit code $LASTEXITCODE."
        }
        if (Test-JustdocsTrue $ModifyPath) {
            Set-JustdocsPath Add
        }
    }
    finally {
        Exit-JustdocsLock
    }
    Write-Output "installed $CommandPath"
    & $CommandPath version
    if (Test-JustdocsTrue $ModifyPath) {
        Write-Output 'User PATH configured; restart the terminal to load it.'
    }
}

function Uninstall-Justdocs {
    if (Test-JustdocsTrue $DryRun) {
        Write-Output "remove $InstallRoot"
        if (Test-JustdocsTrue $ModifyPath) {
            Write-Output "remove $BinDir from the user PATH"
        }
        return
    }
    Enter-JustdocsLock
    try {
        Assert-JustdocsMarker
        if ((Test-Path -LiteralPath $InstallRoot) -and -not (Test-Path -LiteralPath $ManagedFile -PathType Leaf)) {
            throw "refusing to remove unmanaged install root: $InstallRoot"
        }
        if (Test-Path -LiteralPath $InstallRoot) {
            $Marker = (Get-Content -LiteralPath $ManagedFile -Raw).Trim()
            if ($Marker -ne 'justdocs-managed-v1') {
                throw "invalid install ownership marker: $ManagedFile"
            }
            Assert-JustdocsOwnedCommand
            Remove-Item -LiteralPath $InstallRoot -Recurse -Force
        }
        if (Test-JustdocsTrue $ModifyPath) {
            Set-JustdocsPath Remove
        }
    }
    finally {
        Exit-JustdocsLock
    }
    Write-Output "uninstalled $Package"
}

$script:PythonCommand = Resolve-JustdocsPython
$script:Lock = $null
Assert-JustdocsBoolean 'JUSTDOCS_INSTALL_DRY_RUN' $DryRun
Assert-JustdocsBoolean 'JUSTDOCS_MODIFY_PATH' $ModifyPath
Assert-JustdocsInstallRoot
Invoke-JustdocsPython @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)')

switch ($Action) {
    'install' { Install-Justdocs }
    'uninstall' { Uninstall-Justdocs }
    default { throw "unsupported JUSTDOCS_INSTALL_ACTION '$Action': expected install or uninstall" }
}
