param(
  [Parameter(Mandatory = $true)][string]$Workspace,
  [Parameter(Mandatory = $true)][string]$Python,
  [switch]$Force
)
# Thin Windows wrapper: the real work is scripts/setup.py (cross-platform,
# idempotent). ASCII-only on purpose so Windows PowerShell 5.1 parses this file
# correctly regardless of the console code page.
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($Workspace)
$script = Join-Path $PSScriptRoot 'setup.py'
$arguments = @($script, '--workspace', $taskRoot, '--python', $Python)
if ($Force) { $arguments += '--force' }
& $Python @arguments
exit $LASTEXITCODE
