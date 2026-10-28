param(
    [Parameter(Mandatory=$true)][string]$Workspace,
    [Parameter(Mandatory=$true)][string]$Python
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($Workspace)
if (-not [IO.Path]::IsPathRooted($Workspace)) { throw 'Use an absolute workspace path.' }
$driveRoot = [IO.Path]::GetPathRoot($taskRoot)
if ($driveRoot.TrimEnd('\') -ieq $env:SystemDrive) { throw 'Choose a data drive, not the system drive.' }
if ($taskRoot.TrimEnd('\') -eq $driveRoot.TrimEnd('\')) { throw 'Choose a folder, not a drive root.' }
if (-not (Test-Path -LiteralPath $driveRoot)) { throw 'Selected drive does not exist.' }
$env:TEMP = Join-Path $taskRoot 'tools\temp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:HOME = Join-Path $taskRoot 'tools\user'
$env:USERPROFILE = $env:HOME
$env:APPDATA = Join-Path $env:HOME 'AppData\Roaming'
$env:LOCALAPPDATA = Join-Path $env:HOME 'AppData\Local'
$env:PIP_CACHE_DIR = Join-Path $taskRoot 'tools\cache\pip'
$env:XDG_CACHE_HOME = Join-Path $taskRoot 'tools\cache'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:NVIDIA_TF32_OVERRIDE = '0'
New-Item -ItemType Directory -Force -Path $env:TEMP,$env:HOME,$env:APPDATA,$env:LOCALAPPDATA,$env:PIP_CACHE_DIR | Out-Null
$scripts = Join-Path $PSScriptRoot 'video-hardsub-extract\scripts'
Push-Location -LiteralPath $taskRoot
try {
    & $Python -B (Join-Path $scripts 'setup.py') --workspace $taskRoot --python $Python
    if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed; inspect the preceding error.' }
    $venvPython = Join-Path $taskRoot 'tools\hardsub-venv\Scripts\python.exe'
    & $venvPython -B (Join-Path $scripts 'install_local.py') --workspace $taskRoot
    if ($LASTEXITCODE -ne 0) { throw 'Local application installation failed.' }
} finally { Pop-Location }
